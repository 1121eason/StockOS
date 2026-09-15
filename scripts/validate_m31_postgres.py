"""Actual PostgreSQL migration/replay/immutability tests and original-row preservation."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from run_m31 import run, save
from sqlalchemy import inspect, text

from valuation_engine.config import Settings
from valuation_engine.db.session import engine

OUT = Path("data/m31/postgresql")
CORE = "postgresql+psycopg://postgres@127.0.0.1:55439/qve_verified"
LABELS = "postgresql+psycopg://postgres@127.0.0.1:55439/qve_labels"


def originals(url, baseline=None):
    result = {}
    eng = engine(url)
    with eng.connect() as conn:
        for name in inspect(conn).get_table_names():
            if name == "alembic_version" or baseline is not None and name not in baseline:
                continue
            columns = (
                baseline[name]["columns"]
                if baseline
                else [c["name"] for c in inspect(conn).get_columns(name)]
            )
            maximum = (
                baseline[name]["max_id"]
                if baseline
                else conn.scalar(text(f'SELECT max(id) FROM "{name}"'))
            )
            rows = (
                list(
                    conn.execute(
                        text(
                            f'SELECT {",".join(columns)} FROM "{name}" WHERE id<=:maximum ORDER BY id'
                        ),
                        {"maximum": maximum},
                    )
                )
                if maximum is not None
                else []
            )
            result[name] = {
                "columns": columns,
                "max_id": maximum,
                "rows": len(rows),
                "sha256": hashlib.sha256(
                    json.dumps([tuple(r) for r in rows], sort_keys=True, default=str).encode()
                ).hexdigest(),
            }
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("qve_verified", "qve_labels"):
        target = Path(f"data/m31/pre-m31-{name}.dump")
        if not target.exists():
            with target.open("wb") as stream:
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        "stockos-m11-postgres",
                        "pg_dump",
                        "-U",
                        "postgres",
                        "-d",
                        name,
                        "-Fc",
                    ],
                    stdout=stream,
                    check=True,
                )
    baseline_path = OUT / "original-row-baseline.json"
    before = (
        json.loads(baseline_path.read_text())
        if baseline_path.exists()
        else {name: originals(url) for name, url in (("core", CORE), ("labels", LABELS))}
    )
    save(OUT, "original-row-baseline", before)
    summary = run(
        Settings(qve_database_url=CORE, qve_label_database_url=LABELS),
        OUT,
        datetime.fromisoformat("2026-09-12T00:00:00+00:00"),
    )
    after = {
        name: originals(url, before[name]) for name, url in (("core", CORE), ("labels", LABELS))
    }
    assert after == before
    save(OUT, "preservation", {"all_original_rows_unchanged": True, "original_tables": before})
    test = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        env={**os.environ, "QVE_TEST_POSTGRES_URL": CORE},
        capture_output=True,
        text=True,
    )
    (OUT / "test-results.txt").write_text(test.stdout + test.stderr)
    with engine(CORE).connect() as conn:
        receipt = {
            "server_version": conn.scalar(text("select version()")),
            "migration": conn.scalar(text("select version_num from alembic_version")),
            "test_exit_code": test.returncode,
            "test_summary": test.stdout.strip().splitlines()[-1],
            "summary": summary,
        }
    save(OUT, "validation", receipt)
    print(json.dumps(receipt, indent=2))
    raise SystemExit(test.returncode)


if __name__ == "__main__":
    main()
