from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from valuation_engine.config import Settings
from valuation_engine.db.schema import Filing, FinancialFact, SourceDocument
from valuation_engine.ingestion.http import SourceClient
from valuation_engine.ingestion.sec import ingest_sec
from valuation_engine.normalization.quarterly import PointInTimeRepository


def payloads():
    # Explicitly synthetic HTTP contract fixtures; never included in research data.
    a = "0001045810-23-000001"
    b = "0001045810-23-000002"
    submissions = {
        "filings": {
            "recent": {
                "accessionNumber": [a, b],
                "form": ["10-Q", "10-Q"],
                "filingDate": ["2023-05-25", "2023-08-24"],
                "reportDate": ["2023-04-30", "2023-07-30"],
                "acceptanceDateTime": ["2023-05-25T12:00:00Z", "2023-08-24T12:00:00Z"],
                "primaryDocument": ["q1.htm", "q2.htm"],
            },
            "files": [],
        }
    }
    values = [
        {"start": "2023-01-30", "end": "2023-04-30", "val": 100, "accn": a, "fy": 2024, "fp": "Q1"},
        {"start": "2023-01-30", "end": "2023-07-30", "val": 260, "accn": b, "fy": 2024, "fp": "Q2"},
        {"start": "2023-01-30", "end": "2023-04-30", "val": 101, "accn": b, "fy": 2024, "fp": "Q2"},
    ]
    facts = {
        "facts": {
            "us-gaap": {"NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": values}}}
        }
    }
    return submissions, facts


def test_sec_http_ingestion_and_idempotency(db, tmp_path):
    submissions, facts = payloads()
    calls = []

    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(
            200, json=facts if "companyfacts" in str(request.url) else submissions
        )

    client = SourceClient(client=httpx.Client(transport=httpx.MockTransport(handle)))
    settings = Settings(qve_raw_dir=tmp_path / "raw", sec_user_agent=None)
    result = ingest_sec(db, settings, client, download_filings=False)
    assert result["created"] == 3
    assert result["filings_created"] == 2 and result["documents_created"] == 4
    db.commit()
    second = ingest_sec(db, settings, client, download_filings=False)
    assert second["created"] == 0 and second["skipped"] == 3
    assert {
        key: second[key] for key in ("filings_created", "facts_created", "documents_created")
    } == {"filings_created": 0, "facts_created": 0, "documents_created": 0}
    assert second["filings_skipped"] == 2 and second["documents_skipped"] == 4
    assert db.scalar(select(func.count()).select_from(Filing)) == 2
    assert db.scalar(select(func.count()).select_from(FinancialFact)) == 3
    assert db.scalar(select(func.count()).select_from(SourceDocument)) == 4
    assert len(calls) == 4
    repo = PointInTimeRepository(db, 1)
    before = datetime.fromisoformat("2023-08-24T12:02:59+00:00")
    after = datetime.fromisoformat("2023-08-24T12:03:00+00:00")
    assert repo.quarter(2024, 2, before) is None
    q = repo.quarter(2024, 2, after)
    assert q.value("ocf") == Decimal(159)  # same-filing Q1 comparative, not stale 100
    first = repo.quarter(2024, 1, after)
    assert first.value("ocf") == Decimal(100)  # original retained
    assert all(
        f.fiscal_quarter == 1
        for f in db.scalars(
            select(FinancialFact).where(FinancialFact.period_end == datetime(2023, 4, 30).date())
        )
    )


def test_missing_user_agent_fails_before_network(db, tmp_path):
    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        ingest_sec(db, Settings(sec_user_agent=None, _env_file=None, qve_raw_dir=tmp_path))


def test_http_error_not_silent():
    client = SourceClient(
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403)))
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.get("https://example.test/blocked")


def test_sec_primary_filing_bytes_and_accession_uniqueness(db, tmp_path):
    submissions, facts = payloads()

    def handle(request):
        url = str(request.url)
        if "/Archives/" in url:
            return httpx.Response(
                200, content=b"<html>Explicitly synthetic SEC primary filing fixture</html>"
            )
        return httpx.Response(200, json=facts if "companyfacts" in url else submissions)

    client = SourceClient(client=httpx.Client(transport=httpx.MockTransport(handle)))
    settings = Settings(qve_raw_dir=tmp_path / "raw")
    first = ingest_sec(db, settings, client)
    second = ingest_sec(db, settings, client)
    assert first["primary_documents_created"] == 2 and not first["errors"]
    assert second["primary_documents_created"] == 0 and second["created"] == 0
    assert db.scalar(select(func.count(func.distinct(Filing.accession_number)))) == 2
    assert (
        db.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(SourceDocument.document_type == "SEC primary filing")
        )
        == 2
    )
