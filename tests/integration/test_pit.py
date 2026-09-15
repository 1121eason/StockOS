from datetime import datetime
from decimal import Decimal as D

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from valuation_engine.db.schema import ForecastSnapshot, FutureOutcome
from valuation_engine.db.store import company
from valuation_engine.features.engine import compute
from valuation_engine.forecasts.baseline import forecast, historical_forecast
from valuation_engine.normalization.quarterly import PointInTimeRepository

ASOF = datetime.fromisoformat("2023-09-01T00:00:00+00:00")


def test_no_future_filing_and_restatement(db, add):
    original = add("revenue", 100)
    add(
        "revenue",
        150,
        available="2023-12-01T00:00:00+00:00",
        url="https://example.test/restatement",
    )
    repo = PointInTimeRepository(db, company(db).id)
    assert repo.quarter(2024, 1, datetime.fromisoformat("2023-05-24T20:19:59+00:00")) is None
    assert repo.quarter(2024, 1, ASOF).value("revenue") == D(100)
    late = datetime.fromisoformat("2024-01-01T00:00:00+00:00")
    assert repo.quarter(2024, 1, late).value("revenue") == D(100)
    assert repo.quarter(2024, 1, late, "latest_restated").value("revenue") == D(150)
    assert repo.quarter(2024, 1, ASOF).metrics["revenue"].fact_ids == (original.id,)


def test_quarter_ytd_and_nonadditive(db, add):
    add("ocf", 100)
    add(
        "ocf",
        260,
        fq=2,
        kind="ytd",
        available="2023-08-24T20:00:00+00:00",
        url="https://example.test/q2",
    )
    add("capex", 10)
    add(
        "capex",
        40,
        fq=2,
        kind="ytd",
        available="2023-08-24T20:00:00+00:00",
        url="https://example.test/q2",
    )
    add("eps_diluted", 2)
    add(
        "eps_diluted",
        7,
        fq=2,
        kind="ytd",
        available="2023-08-24T20:00:00+00:00",
        url="https://example.test/q2",
    )
    q = PointInTimeRepository(db, company(db).id).quarter(2024, 2, ASOF)
    assert q.value("ocf") == D(160)
    assert q.value("capex") == D(30)
    assert q.value("fcf") == D(130)
    assert q.value("eps_diluted") is None
    assert q.metrics["ocf"].formula == "current_ytd_minus_previous_ytd"


def test_missing_ytd_base_never_zero_filled(db, add):
    add("ocf", 260, fq=2, kind="ytd")
    q = PointInTimeRepository(db, company(db).id).quarter(2024, 2, ASOF)
    assert q.value("ocf") is None


def test_ytd_cannot_use_future_prior_quarter_revision(db, add):
    add("ocf", 260, fq=2, kind="ytd")
    add("ocf", 100, available="2023-12-01T00:00:00+00:00")
    q = PointInTimeRepository(db, company(db).id).quarter(2024, 2, ASOF)
    assert q.value("ocf") is None


def test_q4_annual_subtraction(db, add):
    add("ocf", 600, fq=3, kind="ytd", available="2024-02-01T00:00:00+00:00")
    add("ocf", 1000, fq=4, kind="annual", available="2024-03-01T00:00:00+00:00")
    q = PointInTimeRepository(db, company(db).id).quarter(
        2024, 4, datetime.fromisoformat("2024-04-01T00:00:00+00:00")
    )
    assert q.value("ocf") == D(400)


def test_db_rejects_raw_fact_mutation(db, add):
    add("revenue", 100)
    db.commit()
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("UPDATE financial_facts SET value=900"))
    db.rollback()
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("DELETE FROM financial_facts"))


def test_forecasts_append_and_replay_not_historical(db, add):
    for m, v in {
        "revenue": 1000,
        "gross_profit": 700,
        "operating_expenses": 200,
        "operating_income": 500,
        "pretax_income": 520,
        "tax_expense": 104,
        "diluted_shares": 100,
        "ocf": 450,
        "capex": 50,
    }.items():
        add(m, v)
    repo = PointInTimeRepository(db, company(db).id)
    q = repo.quarter(2024, 1, ASOF)
    snapshot = repo.save(q)
    a = forecast(db, snapshot, ASOF)
    b = forecast(db, snapshot, ASOF)
    assert a.id != b.id and a.eps == D("4.16") and a.fcf == D(400)
    assert a.generated_kind == "historical_replay"
    assert historical_forecast(db, company(db).id, "FY2024-Q2", ASOF) is None
    assert len(db.scalars(select(ForecastSnapshot)).all()) == 2
    db.commit()
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("UPDATE forecast_snapshots SET eps=999"))


def test_future_outcomes_not_in_feature_database(db, add):
    add("revenue", 100)
    with pytest.raises(DBAPIError, match="no such table|does not exist"):
        db.execute(select(FutureOutcome))
    db.rollback()


def test_feature_query_allowlist(db, add):
    from sqlalchemy import event

    for fy, fq, v in [(2023, 1, 100), (2024, 1, 140)]:
        for m, n in {
            "revenue": v,
            "gross_profit": v * D(".6"),
            "operating_income": v * D(".4"),
            "ocf": 20,
            "capex": 5,
        }.items():
            add(m, n, fy=fy, fq=fq)
    queries = []

    @event.listens_for(db.bind, "before_cursor_execute")
    def capture(_c, _cur, statement, _p, _ctx, _many):
        queries.append(statement)

    repo = PointInTimeRepository(db, company(db).id)
    q = repo.quarter(2024, 1, ASOF)
    a = compute(repo, q)
    b = compute(repo, q)
    assert a == b and a.values["revenue_yoy"] == D(".4")
    assert a.values["gross_margin"] == D(".6")
    assert not any("future_outcomes" in sql or "market_prices" in sql for sql in queries)


def test_future_guidance_cannot_enter_forecast(db, add):
    from valuation_engine.db.schema import GuidanceItem

    source = add("revenue", 100)
    db.add(
        GuidanceItem(
            identity_key="synthetic future guidance",
            company_id=source.company_id,
            fiscal_year=2024,
            fiscal_quarter=1,
            guidance_for_period="FY2024-Q2",
            metric_name="revenue",
            mid_value=D(999),
            unit="USD",
            guidance_type="test",
            raw_text="synthetic fixture",
            available_at=datetime.fromisoformat("2023-12-01T00:00:00+00:00"),
            source_document_id=source.source_document_id,
        )
    )
    repo = PointInTimeRepository(db, source.company_id)
    result = forecast(db, repo.save(repo.quarter(2024, 1, ASOF)), ASOF)
    assert result.revenue == D(100)


def test_conflicting_equal_priority_facts_are_unavailable(db, add):
    add("revenue", 100)
    add("revenue", 999, url="https://example.test/conflict")
    q = PointInTimeRepository(db, company(db).id).quarter(2024, 1, ASOF)
    assert q.value("revenue") is None


def test_earliest_derived_quarter_not_replaced_by_later_direct_report(db, add):
    add("ocf", 100)
    add(
        "ocf",
        260,
        fq=2,
        kind="ytd",
        available="2023-08-24T20:00:00+00:00",
        url="https://example.test/ytd",
    )
    add(
        "ocf",
        180,
        fq=2,
        available="2023-12-01T00:00:00+00:00",
        url="https://example.test/later-direct",
    )
    repo = PointInTimeRepository(db, company(db).id)
    late = datetime.fromisoformat("2024-01-01T00:00:00+00:00")
    assert repo.quarter(2024, 2, late).value("ocf") == D(160)
    assert repo.quarter(2024, 2, late, "latest_restated").value("ocf") == D(180)
