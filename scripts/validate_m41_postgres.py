"""Actual PostgreSQL M4.1 migration and tests, with pre-M4.1 row preservation."""

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text
from validate_m3_postgres import CORE, LABELS, originals

from valuation_engine.cli.main import migrate
from valuation_engine.config import Settings
from valuation_engine.db.session import engine

OUT = Path("data/m41/postgresql")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("qve_verified", "qve_labels"):
        target = Path(f"data/m41/pre-m41-{name}.dump")
        if not target.exists() or target.stat().st_size == 0:
            temporary = target.with_suffix(".tmp")
            with temporary.open("wb") as stream:
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
            temporary.replace(target)
    baseline = OUT / "original-row-baseline.json"
    before = (
        json.loads(baseline.read_text())
        if baseline.exists()
        else {name: originals(url) for name, url in [("core", CORE), ("labels", LABELS)]}
    )
    baseline.write_text(json.dumps(before, indent=2) + "\n")
    migrate(Settings(qve_database_url=CORE, qve_label_database_url=LABELS))
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        env={**os.environ, "QVE_TEST_POSTGRES_URL": CORE},
        capture_output=True,
        text=True,
    )
    (OUT / "test-results.txt").write_text(result.stdout + result.stderr)
    after = {
        name: originals(url, before[name]) for name, url in [("core", CORE), ("labels", LABELS)]
    }
    assert before == after
    with engine(CORE).connect() as conn:
        receipt = {
            "server_version": conn.scalar(text("select version()")),
            "migration": conn.scalar(text("select version_num from alembic_version")),
            "test_exit_code": result.returncode,
            "test_summary": result.stdout.strip().splitlines()[-1],
            "all_original_rows_unchanged": True,
            "original_tables": before,
        }
    (OUT / "validation.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "original_tables"}, indent=2))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
