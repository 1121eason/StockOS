"""Validate the additive share migration and closure workflow on the isolated live PG."""

import json
import os
import subprocess
import sys
from pathlib import Path

from close_m11 import run
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from valuation_engine.cli.main import migrate
from valuation_engine.config import Settings
from valuation_engine.db.schema import SourceDocument
from valuation_engine.db.session import engine
from valuation_engine.db.store import read_document
from valuation_engine.ingestion.sec import ingest_sec

out = Path("data/m11-closure/postgresql")
out.mkdir(parents=True, exist_ok=True)
backup = Path("data/m11-closure/pre-closure-qve_verified.dump")
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
migrate(settings)
with Session(engine("sqlite:///data/qve.db")) as source:
    cache = {
        doc.source_url: read_document(doc)
        for doc in source.scalars(
            select(SourceDocument)
            .where(SourceDocument.source_provider == "SEC")
            .order_by(SourceDocument.id)
        )
    }


class CachedSEC:
    def get(self, url):
        if url not in cache:
            raise ValueError(f"SEC URL not present in verified local cache: {url}")
        return cache[url]


replay = {"status": "unavailable", "reason": "No actual SEC cache exists"}
if cache:
    with Session(engine(url)) as db:
        replay = {
            "kind": "offline_replay_of_actual_SEC_bytes",
            **ingest_sec(db, settings, CachedSEC()),
        }
        db.commit()
first = run(settings, out)
second = run(settings, Path("data/m11-closure/postgresql-second"))
assert first["counts"] == second["counts"]
assert first["coverage"] == second["coverage"]
test = subprocess.run(
    [sys.executable, "-m", "pytest", "-q"],
    env=dict(os.environ, QVE_TEST_POSTGRES_URL=url),
    text=True,
    capture_output=True,
)
(out / "test-results.txt").write_text(test.stdout + test.stderr)
with Session(engine(url)) as db:
    receipt = {
        "migration": db.scalar(text("select version_num from alembic_version")),
        "server_version": db.scalar(text("select version()")),
        "test_exit_code": test.returncode,
        "test_summary": test.stdout.splitlines()[-1] if test.stdout else test.stderr,
        "counts_idempotent": True,
        "first_counts": first["counts"],
        "second_counts": second["counts"],
        "sec_cache_replay": replay,
        "coverage": second["coverage"],
    }
(out / "validation.json").write_text(json.dumps(receipt, indent=2, default=str) + "\n")
print(json.dumps(receipt, indent=2))
raise SystemExit(test.returncode)
