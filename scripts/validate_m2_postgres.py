"""Run frozen M2 replay and tests on the existing isolated real PostgreSQL benchmark."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from run_m2 import run
from sqlalchemy import text
from sqlalchemy.orm import Session

from valuation_engine.config import Settings
from valuation_engine.db.session import engine

out = Path("data/m2/postgresql")
out.mkdir(parents=True, exist_ok=True)
backup = Path("data/m2/pre-m2-qve_verified.dump")
if not backup.exists():
    with backup.open("wb") as stream:
        subprocess.run(
            [
                "docker",
                "exec",
                "stockos-m11-postgres",
                "pg_dump",
                "-U",
                "postgres",
                "-d",
                "qve_verified",
                "-Fc",
            ],
            stdout=stream,
            check=True,
        )
url = "postgresql+psycopg://postgres@127.0.0.1:55439/qve_verified"
settings = Settings(
    qve_database_url=url,
    qve_label_database_url="postgresql+psycopg://postgres@127.0.0.1:55439/qve_labels",
)
summary = run(settings, out, datetime.fromisoformat("2026-09-12T00:00:00+00:00"), repeat=True)
test = subprocess.run(
    [sys.executable, "-m", "pytest", "-q"],
    env=dict(os.environ, QVE_TEST_POSTGRES_URL=url),
    capture_output=True,
    text=True,
)
(out / "test-results.txt").write_text(test.stdout + test.stderr)
with Session(engine(url)) as db:
    receipt = dict(
        migration=db.scalar(text("select version_num from alembic_version")),
        server_version=db.scalar(text("select version()")),
        test_exit_code=test.returncode,
        test_summary=test.stdout.strip().splitlines()[-1],
        coverage=summary["coverage"],
        gates=summary["gates"],
    )
(out / "validation.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt, indent=2))
raise SystemExit(test.returncode)
