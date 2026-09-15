"""Run migrations, real cached source ingestion, PIT/features and test suite on local PG."""

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import psycopg
from harden_m11 import run
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from valuation_engine.cli.main import migrate
from valuation_engine.config import Settings
from valuation_engine.db.schema import MarketPrice
from valuation_engine.db.session import engine
from valuation_engine.ingestion.market import PriceBar, ingest_prices

with psycopg.connect("postgresql://postgres@127.0.0.1:55439/postgres", autocommit=True) as admin:
    if not admin.execute("SELECT 1 FROM pg_database WHERE datname = 'qve_verified'").fetchone():
        admin.execute("CREATE DATABASE qve_verified")

url = "postgresql+psycopg://postgres@127.0.0.1:55439/qve_verified"
settings = Settings(
    qve_database_url=url,
    qve_label_database_url="postgresql+psycopg://postgres@127.0.0.1:55439/qve_labels",
)
migrate(settings)
with Session(engine("sqlite:///data/qve.db")) as source:
    bars = [
        PriceBar.model_validate({k: getattr(r, k) for k in PriceBar.model_fields})
        for r in source.scalars(select(MarketPrice))
    ]


class CachedPrices:
    def fetch(self, ticker, start, end):
        return bars


with Session(engine(url)) as db:
    result = ingest_prices(db, CachedPrices(), date(2020, 1, 1), date(2026, 9, 12))
    db.commit()
print("PostgreSQL actual historical price replay:", result, flush=True)
report = run(settings, Path("data/m11/postgresql"))
second = run(settings, Path("data/m11/postgresql-second"))
print("PostgreSQL source replay:", report["ir"], flush=True)
print("Second source replay:", second["ir"], flush=True)
env = dict(os.environ, QVE_TEST_POSTGRES_URL=url)
test = subprocess.run(
    [sys.executable, "-m", "pytest", "-q"], env=env, text=True, capture_output=True
)
Path("data/m11/postgresql/test-results.txt").write_text(test.stdout + test.stderr)
with Session(engine(url)) as db:
    details = {
        "server_version": db.scalar(text("select version()")),
        "migration": db.scalar(text("select version_num from alembic_version")),
        "test_exit_code": test.returncode,
        "source_replay": result,
        "first_counts": report["counts"],
        "second_counts": second["counts"],
        "counts_idempotent": report["counts"] == second["counts"],
        "actual_ir_replay_first": report["ir"],
        "actual_ir_replay_second": second["ir"],
        "network_sources": "Real NVIDIA issuer bytes previously downloaded and hash-verified; SEC online ingestion pending user identity",
    }
Path("data/m11/postgresql/validation.json").write_text(json.dumps(details, indent=2, default=str))
print(test.stdout, test.stderr, flush=True)
raise SystemExit(test.returncode)
