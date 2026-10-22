"""New-quarter boundaries on synthetic filings; no live calls or formal writes."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import event, select
from test_research import populate
from test_research import synthetic as synthetic
from test_sec import payloads

from valuation_engine.config import Settings
from valuation_engine.db.schema import FinancialFact
from valuation_engine.db.store import add_fact, company, document, read_document
from valuation_engine.hardening.shares import add_share_observation
from valuation_engine.ingestion.http import SourceClient
from valuation_engine.ingestion.sec import ingest_sec
from valuation_engine.regime.confidence import POLICY
from valuation_engine.regime.features import extract
from valuation_engine.regime.service import replay_runs
from valuation_engine.research.deployment import refresh_source_hashes
from valuation_engine.research.financial_refresh import RefreshBlocked, cohort, reconcile_release
from valuation_engine.research.service import build_forecast, compare_forecasts
from valuation_engine.research.valuation import build_live_valuation, build_valuation
from valuation_engine.time import calculate_next_tradable_timestamp


def test_live_rebuild_uses_same_dcf_without_market_or_ai_reads(db, synthetic):
    history = populate(synthetic, count=9)
    runs = [build_forecast(db, 1, calculate_next_tradable_timestamp(t)) for t, _ in history[-3:]]
    released, source = history[-1]
    add_share_observation(
        db,
        source=source,
        share_count=D(9000),
        shares_as_of_date=released.date(),
        published_at=released,
        available_at=released,
        source_type="official_disclosure",
        basis_date=released.date(),
    )
    at = runs[-1].forecast_as_of + timedelta(days=1)
    live = build_forecast(db, 1, at, checkpoint="live")
    with pytest.raises(ValueError):
        build_valuation(db, live)
    with pytest.raises(ValueError):
        extract(db, live, runs[:-1], POLICY)
    statements = []

    def guard(conn, cursor, statement, parameters, context, executemany):
        assert not any(
            k in statement.lower() for k in ("market_prices", "ai_features", "future_outcomes")
        )
        statements.append(statement)

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", guard)
    try:
        value = build_live_valuation(db, live)
        rows, _, _ = replay_runs(db, 1, [*runs[:-1], live], POLICY, allow_live=True)
    finally:
        event.remove(connection, "before_cursor_execute", guard)
    assert value.dcf_base is not None and value.dcf_base > 0 and value.ntm_pe is None
    assert statements and rows[-1].forecast_run_id == live.id
    assert cohort(db, 1, at)[live.metadata_json["anchor"]].id == live.id
    with pytest.raises(ValueError, match="unique chronological"):
        replay_runs(db, 1, [*runs, live], POLICY, allow_live=True)
    compared = compare_forecasts(db, live, runs[-2])
    assert all(item["target"].startswith("FY") for item in compared["comparisons"])


def sec_fixture(db, tmp_path, *, observed=None):
    submissions, facts = payloads()
    values = facts["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]
    for tag in (
        "Revenues",
        "OperatingIncomeLoss",
        "NetIncomeLoss",
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ):
        facts["facts"]["us-gaap"][tag] = values
    client = SourceClient(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda req: httpx.Response(
                    200, json=facts if "companyfacts" in str(req.url) else submissions
                )
            )
        )
    )
    settings = Settings(_env_file=None, qve_raw_dir=tmp_path / "raw")
    ingest_sec(
        db,
        settings,
        client,
        download_filings=False,
        period_end=date(2023, 7, 30),
        observed_at=observed,
    )
    return client, settings


def test_sec_live_capture_does_not_backdate_new_facts_or_rewrite_old(db, tmp_path):
    observed = datetime(2026, 10, 22, tzinfo=UTC)
    client, settings = sec_fixture(db, tmp_path, observed=observed)
    facts = list(db.scalars(select(FinancialFact)))
    assert facts and all(f.available_at >= observed for f in facts)
    before = {f.id: f.available_at for f in facts}
    ingest_sec(
        db,
        settings,
        client,
        download_filings=False,
        period_end=date(2023, 7, 30),
        observed_at=observed + timedelta(days=1),
    )
    assert {f.id: f.available_at for f in db.scalars(select(FinancialFact))} == before


@pytest.mark.parametrize("wrong", [False, True])
def test_sec_reconciliation_normalizes_ytd_and_rejects_conflicts(db, tmp_path, wrong):
    sec_fixture(db, tmp_path)
    co = company(db)
    at = datetime(2023, 8, 24, 13, tzinfo=UTC)
    doc = document(
        db,
        tmp_path / "raw",
        b"synthetic release",
        url="https://example.test/release",
        company_id=co.id,
        provider="NVIDIA IR",
        kind="test",
        published_at=at,
        metadata={"fiscal_year": 2024, "fiscal_quarter": 2},
    )
    for metric in ("revenue", "operating_income", "net_income", "ocf", "capex"):
        add_fact(
            db,
            company_id=co.id,
            source_document_id=doc.id,
            metric_name=metric,
            taxonomy_name="synthetic:" + metric,
            value=D(160 if wrong and metric == "ocf" else 159),
            unit="USD",
            period_start=date(2023, 5, 1),
            period_end=date(2023, 7, 30),
            fiscal_year=2024,
            fiscal_quarter=2,
            duration_kind="quarter",
            available_at=at,
            reported_at=at,
            source_priority=20,
            formula_version="synthetic",
            metadata_json={},
        )
    if wrong:
        with pytest.raises(RefreshBlocked, match="financial_conflict"):
            reconcile_release(db, co, doc, {"end": date(2023, 7, 30)}, at)
    else:
        result = reconcile_release(db, co, doc, {"end": date(2023, 7, 30)}, at)
        assert result["status"] == "matched" and len(result["comparisons"]) == 5
        ocf = next(r for r in result["comparisons"] if r["metric"] == "ocf")
        assert len(ocf["sec_fact_ids"]) == 2 and ocf["formula"]


def test_isolated_source_read_never_falls_back_to_original_path(tmp_path):
    raw = b"synthetic original bytes"
    import hashlib

    identity = hashlib.sha256(raw).hexdigest()
    original = tmp_path / "original"
    original.write_bytes(raw)
    source = SimpleNamespace(raw_path=str(original), content_hash=identity, id=1)
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    with pytest.raises(ValueError, match="Isolated source"):
        read_document(source, isolated, strict_root=True)
    (isolated / identity).write_bytes(raw)
    assert read_document(source, isolated, strict_root=True) == raw
    assert original.read_bytes() == raw


def test_seed_includes_older_ir_sources_needed_for_future_guidance(db, synthetic, tmp_path):
    history = populate(synthetic, count=3)
    db.commit()
    hashes = refresh_source_hashes(tmp_path / "test.db", tmp_path)
    assert hashes == {doc.content_hash for _, doc in history}
    (tmp_path / history[0][1].content_hash).unlink()
    with pytest.raises(FileNotFoundError):
        refresh_source_hashes(tmp_path / "test.db", tmp_path)
