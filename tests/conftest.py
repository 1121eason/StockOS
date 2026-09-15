import os
import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from valuation_engine.db.session import create_test_schema
from valuation_engine.db.store import add_fact, company, document
from valuation_engine.ingestion.ir import fiscal_start


@pytest.fixture
def db(tmp_path):
    postgres = os.environ.get("QVE_TEST_POSTGRES_URL")
    admin = None
    schema = "pytest_" + uuid.uuid4().hex
    if postgres:
        admin = create_engine(postgres)
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(postgres).update_query_dict({"options": f"-csearch_path={schema}"})
        engine = create_test_schema(url)
    else:
        engine = create_test_schema(f"sqlite:///{tmp_path}/test.db")
    with Session(engine) as db:
        yield db
    engine.dispose()
    if admin:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def add(db, tmp_path):
    def create(
        metric,
        value,
        fy=2024,
        fq=1,
        available="2023-05-24T20:20:00+00:00",
        kind="quarter",
        start=None,
        end=None,
        url="https://example.test/synthetic-release",
        taxonomy=None,
        unit="USD",
        provider="synthetic test fixture",
    ):
        from datetime import timedelta

        co = company(db)
        at = datetime.fromisoformat(available)
        doc = document(
            db,
            tmp_path / "raw",
            url.encode(),
            url=url,
            company_id=co.id,
            provider=provider,
            kind="test",
            published_at=at,
        )
        end = (
            end or fiscal_start(fy, fq + 1) - timedelta(days=1)
            if fq < 4
            else end or fiscal_start(fy + 1, 1) - timedelta(days=1)
        )
        start = (
            None
            if kind == "instant"
            else start or fiscal_start(fy, 1 if kind in ("ytd", "annual") else fq)
        )
        return add_fact(
            db,
            company_id=co.id,
            metric_name=metric,
            taxonomy_name=taxonomy or "test:" + metric,
            value=Decimal(str(value)),
            unit=unit,
            period_start=start,
            period_end=end,
            fiscal_year=fy,
            fiscal_quarter=fq,
            duration_kind=kind,
            available_at=at,
            reported_at=at,
            source_document_id=doc.id,
            source_priority=10,
            formula_version="test-v1",
            metadata_json={},
        )[0]

    return create
