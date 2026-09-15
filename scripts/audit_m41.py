"""Preserve all pre-M4 rows and verify the accepted Quant/Regime cohort without AI."""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from valuation_engine.db.session import engine
from valuation_engine.regime.confidence import POLICY
from valuation_engine.regime.service import replay


def main():
    out = Path("data/m41/report")
    rows = {}
    for name in ("qve", "labels"):
        backup = Path(f"data/m41/pre-m41-{name}.db")
        assert backup.is_file()
        with sqlite3.connect(backup) as old, sqlite3.connect(f"data/{name}.db") as new:
            for (table,) in old.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='alembic_version'"
            ):
                columns = [c[1] for c in old.execute(f'PRAGMA table_info("{table}")')]
                data = list(old.execute(f'SELECT * FROM "{table}" ORDER BY id'))
                for row in data:
                    current = new.execute(
                        f'SELECT {",".join(columns)} FROM "{table}" WHERE id=?',
                        (row[columns.index("id")],),
                    ).fetchone()
                    assert current == row, (name, table)
                rows[f"{name}:{table}"] = {"original_rows": len(data), "unchanged": True}
    baseline = json.loads(Path("data/m31/report/history.json").read_text())
    with Session(engine("sqlite:///data/qve.db")) as db:
        records, states, _ = replay(
            db, 1, datetime.fromisoformat(baseline["states"][-1]["as_of"]), POLICY
        )
        assert states == baseline["states"]
        assert [r.id for r in records] == baseline["snapshot_ids"]
        # Nothing new is committed; a re-run must resolve exactly the accepted immutable rows.
        db.rollback()
    archives = {}
    for version in ("m2", "m3", "m31", "m4"):
        receipt = json.loads(Path(f"artifacts/{version}-checksums.json").read_text())
        for name, expected in receipt.items():
            assert (
                hashlib.sha256((Path("artifacts") / name).read_bytes()).hexdigest()
                == expected["sha256"]
            )
            archives[name] = expected["sha256"]
    (out / "preservation.json").write_text(
        json.dumps(
            {
                "original_rows": rows,
                "regime_26_states_and_ids_unchanged": True,
                "prior_archives_unchanged": archives,
            },
            indent=2,
        )
        + "\n"
    )
    print("Original rows, all 26 Regime states/IDs and M2/M3/M3.1 delivery archives preserved.")


if __name__ == "__main__":
    main()
