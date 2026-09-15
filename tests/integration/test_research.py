"""Synthetic financial-only fixtures; none are written to the benchmark databases."""

import ast
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError

from valuation_engine.db.schema import (
    CorporateAction,
    ForecastAssumption,
    GuidanceItem,
    MarketPrice,
    ResearchValuation,
)
from valuation_engine.db.store import add_fact, company, digest, document
from valuation_engine.hardening.availability import add_evidence
from valuation_engine.hardening.basis import build_price_bases
from valuation_engine.hardening.shares import add_share_observation
from valuation_engine.ingestion.ir import fiscal_start
from valuation_engine.normalization.quarterly import prior_period
from valuation_engine.research.forecast import ForecastPolicyV1, aggregate, produce
from valuation_engine.research.inputs import FinancialInputs
from valuation_engine.research.numbers import POLICY, canonical
from valuation_engine.research.service import build_forecast, revisions, stored_periods
from valuation_engine.research.valuation import build_valuation, historical_context
from valuation_engine.time import calculate_next_tradable_timestamp


@pytest.fixture
def synthetic(db, tmp_path):
    co = company(db)

    def create(fy, fq, index=0, release=None, multiplier=D(1)):
        next_fy, next_fq = prior_period(fy, fq, -1)
        end = fiscal_start(next_fy, next_fq) - timedelta(days=1)
        at = release or datetime.combine(
            end + timedelta(days=20), datetime.min.time(), UTC
        ).replace(hour=20)
        raw = f"synthetic-{fy}-{fq}-{at}".encode()
        doc = document(
            db,
            tmp_path,
            raw,
            url=f"https://example.test/synthetic/{fy}/{fq}/{at}",
            company_id=co.id,
            provider="NVIDIA IR",
            kind="synthetic test",
            published_at=at,
            metadata={
                "fiscal_year": fy,
                "fiscal_quarter": fq,
                "publication_date": at.date().isoformat(),
            },
        )
        add_evidence(db, doc, doc, at, "exact", at, ("financial_fact",))
        rev = (D(1000000) + D(index) * 100000) * multiplier
        shares = D(10000) * (1 - D(".001") * index)
        values = {
            "revenue": rev,
            "gross_profit": rev * D(".6"),
            "operating_expenses": rev * D(".2"),
            "operating_income": rev * D(".4"),
            "pretax_income": rev * D(".41"),
            "tax_expense": rev * D(".082"),
            "net_income": rev * D(".328"),
            "diluted_shares": shares,
            "eps_diluted": rev * D(".328") / shares,
            "ocf": rev * D(".38"),
            "capex": rev * D(".03"),
            "accounts_receivable": rev * D(".1"),
            "inventory": rev * D(".05"),
            "cash": D(50000),
            "debt": D(10000),
        }
        for metric, value in values.items():
            instant = metric in ("accounts_receivable", "inventory", "cash", "debt")
            add_fact(
                db,
                company_id=1,
                source_document_id=doc.id,
                metric_name=metric,
                taxonomy_name="synthetic:" + metric,
                value=value,
                unit="shares"
                if metric == "diluted_shares"
                else "USD/shares"
                if metric == "eps_diluted"
                else "USD",
                period_start=None if instant else fiscal_start(fy, fq),
                period_end=end,
                fiscal_year=fy,
                fiscal_quarter=fq,
                duration_kind="instant" if instant else "quarter",
                available_at=at,
                reported_at=at,
                source_priority=10,
                formula_version="synthetic",
                metadata_json={},
            )
        return at, doc

    return create


def populate(synthetic, through=(2024, 1), count=9):
    rows = []
    for i in range(count):
        fy, fq = prior_period(*through, count - i - 1)
        rows.append(synthetic(fy, fq, i))
    return rows


def guide(db, tmp_path, fy, fq, at, metric, value, basis="GAAP", suffix=""):
    target_fy, target_fq = prior_period(fy, fq, -1)
    doc = document(
        db,
        tmp_path,
        ("synthetic guidance" + suffix).encode(),
        url="https://example.test/guidance/" + str((fy, fq, metric, basis, suffix)),
        company_id=1,
        provider="synthetic structured guidance",
        kind="test",
        published_at=at,
    )
    g = GuidanceItem(
        identity_key=digest([doc.id, metric, value]),
        company_id=1,
        fiscal_year=fy,
        fiscal_quarter=fq,
        guidance_for_period=f"FY{target_fy}-Q{target_fq}",
        metric_name=metric,
        low_value=D(value) * D(".98"),
        mid_value=D(value),
        high_value=D(value) * D("1.02"),
        unit="ratio" if metric in ("gross_margin", "tax_rate") else "USD",
        guidance_type="synthetic",
        basis=basis,
        raw_text="synthetic fixture only",
        available_at=at,
        source_document_id=doc.id,
    )
    db.add(g)
    db.flush()
    return g


def test_forecast_future_filing_and_guidance_do_not_change_2023_forecast(db, synthetic, tmp_path):
    released, _ = populate(synthetic)[-1]
    at = calculate_next_tradable_timestamp(released)
    run = build_forecast(db, 1, at)
    periods = canonical(stored_periods(db, run.id))
    future, doc = synthetic(
        2025, 1, 100, release=datetime(2024, 5, 25, 20, tzinfo=UTC), multiplier=D(999)
    )
    guide(db, tmp_path, 2024, 1, future, "revenue", "999999999", suffix="future")
    repeated = build_forecast(db, 1, at)
    assert repeated.id == run.id
    assert canonical(stored_periods(db, repeated.id)) == periods
    assert all(
        datetime.fromisoformat(o["available_at"].replace("Z", "+00:00")) <= at
        for o in run.metadata_json["provenance"]["observations"].values()
    )
    assert str(doc.id) not in {
        str(v["source_document_id"])
        for v in run.metadata_json["provenance"]["fact_sources"].values()
    }


@pytest.mark.parametrize("checkpoint", ["first_tradable", "issuer_release", "research_replay"])
def test_equivalent_timezone_inputs_reuse_immutable_run(db, synthetic, checkpoint):
    released, _ = populate(synthetic)[-1]
    at = calculate_next_tradable_timestamp(released) if checkpoint == "first_tradable" else released
    run = build_forecast(db, 1, at, checkpoint)
    original = canonical(stored_periods(db, run.id))
    for zone in (UTC, ZoneInfo("America/New_York"), ZoneInfo("Australia/Brisbane")):
        repeated = build_forecast(db, 1, at.astimezone(zone), checkpoint)
        assert repeated.id == run.id
        assert canonical(stored_periods(db, repeated.id)) == original


def test_guidance_gaap_anchor_raw_bias_and_full_income_path(db, synthetic, tmp_path):
    released, _ = populate(synthetic, count=2)[-1]
    at = calculate_next_tradable_timestamp(released)
    for metric, value in [
        ("revenue", "3000000"),
        ("gross_margin", ".65"),
        ("operating_expenses", "500000"),
        ("tax_rate", ".2"),
    ]:
        guide(db, tmp_path, 2024, 1, released, metric, value)
    guide(db, tmp_path, 2024, 1, released, "operating_expenses", "1", "NON_GAAP", "non-gaap")
    run = build_forecast(db, 1, at)
    q = stored_periods(db, run.id)[0]
    assert (
        q["revenue"] == 3000000
        and q["gross_margin"] == D(".65")
        and q["operating_expenses"] == 500000
    )
    assert q["gross_profit"] == q["revenue"] * q["gross_margin"]
    assert q["operating_income"] == q["gross_profit"] - q["operating_expenses"]
    assert abs(q["net_income"] - q["pre_tax_income"] * (1 - q["tax_rate"])) < D(".00000002")
    assert abs(q["eps"] - q["net_income"] / q["diluted_weighted_shares"]) < D(".00000001")
    assert q["operating_cash_flow"] - q["capex"] == q["free_cash_flow"]
    assert run.metadata_json["guidance_bias"]["revenue"]["status"] == "insufficient_history"
    assert run.metadata_json["raw_guidance"]["revenue"]["midpoint"] == "3000000.00000000"
    assert q["metadata_json"]["intervals"]["revenue"]["status"] == "insufficient_history"


def test_guidance_bias_only_realized_at_cutoff(db, synthetic, tmp_path):
    history = populate(synthetic, count=7)
    for i, (released, _) in enumerate(history[:-1]):
        fy, fq = prior_period(2024, 1, len(history) - i - 1)
        guide(db, tmp_path, fy, fq, released, "revenue", str(1000000 + (i + 1) * 100000))
    at = calculate_next_tradable_timestamp(history[4][0])
    data = FinancialInputs(db, 1, at)
    before = data.guidance_accuracy()["revenue"]
    assert len(before) == 4 and all(x["actual_available_at"] <= at for x in before)
    result = produce(data, ForecastPolicyV1())
    assert result["metadata"]["guidance_bias"]["revenue"]["sample_count"] == 4
    assert result["metadata"]["guidance_bias"]["revenue"]["adjustment"] == 0


def test_immutability_assumptions_and_determinism(db, synthetic):
    released, _ = populate(synthetic, count=2)[-1]
    at = calculate_next_tradable_timestamp(released)
    first = build_forecast(db, 1, at)
    second = build_forecast(db, 1, at)
    assert first.id == second.id
    saved = canonical(stored_periods(db, first.id))
    db.commit()
    db.expire_all()
    assert canonical(stored_periods(db, first.id)) == saved
    assert {r.parameter_name for r in db.scalars(select(ForecastAssumption))} == set(POLICY)
    for table, column, value in [
        ("forecast_runs", "model_name", "'changed'"),
        ("forecast_periods", "eps", "'999'"),
        ("forecast_assumptions", "unit", "'changed'"),
    ]:
        with pytest.raises(DBAPIError, match="immutable"):
            db.execute(text(f"UPDATE {table} SET {column}={value}"))
        db.rollback()


def test_fiscal_roll_and_same_target_revision(db, synthetic):
    releases = populate(synthetic, through=(2024, 4), count=5)
    old = build_forecast(db, 1, calculate_next_tradable_timestamp(releases[-2][0]))
    new = build_forecast(db, 1, calculate_next_tradable_timestamp(releases[-1][0]))
    op, np = stored_periods(db, old.id), stored_periods(db, new.id)
    assert next(p for p in op if p["period_type"] == "FY1")["fiscal_year"] == 2024
    assert next(p for p in np if p["period_type"] == "FY1")["fiscal_year"] == 2025
    assert len(next(p for p in np if p["period_type"] == "NTM")["metadata_json"]["components"]) == 4
    same = next(c for c in revisions(db, new)["comparisons"] if c["new_label"] == "FY1")
    assert same["target"] == "FY2025" and same["previous_label"] == "FY2"
    assert "fiscal_year_model_roll" in same["reasons"]


@pytest.mark.parametrize("day,ratio", [(date(2021, 7, 20), D(4)), (date(2024, 6, 10), D(10))])
def test_forecast_split_basis_preserves_income_and_eps_product(db, synthetic, tmp_path, day, ratio):
    anchor = (2022, 1) if day.year == 2021 else (2025, 1)
    populate(synthetic, through=anchor, count=5)
    before = datetime.combine(day - timedelta(days=1), datetime.min.time(), UTC).replace(hour=18)
    after = before + timedelta(days=2)
    base = produce(FinancialInputs(db, 1, before), ForecastPolicyV1())
    doc = document(
        db,
        tmp_path,
        b"synthetic split",
        url="https://example.test/split",
        company_id=1,
        provider="synthetic",
        kind="test",
        published_at=before,
    )
    db.add(
        CorporateAction(
            identity_key="split",
            company_id=1,
            action_type="split",
            split_date=day,
            effective_date=day - timedelta(days=1),
            ratio_numerator=ratio,
            ratio_denominator=D(1),
            adjustment_factor=ratio,
            announced_at=before - timedelta(days=30),
            source_document_id=doc.id,
            metadata_json={},
        )
    )
    db.flush()
    current = produce(FinancialInputs(db, 1, after), ForecastPolicyV1())
    for a, b in zip(base["periods"], current["periods"], strict=True):
        assert a["revenue"] == b["revenue"]
        assert abs(a["eps"] / ratio - b["eps"]) < D(".00000001")
        assert abs(a["diluted_weighted_shares"] * ratio - b["diluted_weighted_shares"]) < D(
            ".000001"
        )


def test_forecast_has_no_evaluation_price_or_return_access(db, synthetic, monkeypatch):
    released, _ = populate(synthetic, count=2)[-1]
    statements = []

    def guard(conn, cursor, statement, parameters, context, many):
        statements.append(statement.lower())
        if any(
            x in statement.lower()
            for x in (
                "forecast_outcomes",
                "future_outcomes",
                "market_prices",
                "research_valuations",
                "price_bases",
            )
        ):
            raise AssertionError("Forbidden forecast dependency")

    event.listen(db.get_bind(), "before_cursor_execute", guard)
    try:
        run = build_forecast(db, 1, calculate_next_tradable_timestamp(released))
        assert run.generated_kind == "research_reconstructed_internal"
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", guard)
    for path in Path("src/valuation_engine/research").glob("*.py"):
        if path.name in ("valuation.py", "history.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert "evaluation" not in (node.module or "") and "backtest" not in (
                    node.module or ""
                )
                assert not {"FutureOutcome", "ForecastOutcome"}.intersection(
                    n.name for n in node.names
                )
    assert statements


def test_context_low_samples_and_strict_prior_selection(db, synthetic, tmp_path):
    assert historical_context([D(1)], D(2))["percentile"] is None
    assert historical_context([D(1), D(2), D(3), D(4)], D(3))["percentile"] == D(".625")
    released, source = populate(synthetic, count=5)[-1]
    at = calculate_next_tradable_timestamp(released)
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
    db.add(
        MarketPrice(
            company_id=1,
            ticker="NVDA",
            timestamp=at,
            available_at=at + timedelta(hours=7),
            price_type="daily_unadjusted",
            open=D(100),
            high=D(110),
            low=D(90),
            close=D(105),
            adjusted_close=None,
            volume=100,
            currency="USD",
            provider="synthetic",
            retrieved_at=at,
            content_hash="test-price",
        )
    )
    db.flush()
    build_price_bases(db, 1)
    run = build_forecast(db, 1, at)
    value = build_valuation(db, run)
    assert value.ntm_pe is not None and value.dcf_base is not None
    assert value.metadata_json["market_cap"] == "900000.00000000"
    assert value.metadata_json["historical_context"]["ntm_pe"]["sample_count"] == 0
    assert stored_periods(db, run.id)[0]["diluted_weighted_shares"] != 9000
    future, _ = synthetic(2025, 1, 500, release=at + timedelta(days=366))
    add_share_observation(
        db,
        source=source,
        share_count=D(99999999),
        shares_as_of_date=released.date(),
        published_at=future,
        available_at=future,
        source_type="official_disclosure",
        basis_date=released.date(),
    )
    # A later cash/debt/share release and a future valuation row must have no effect at the old cutoff.
    future_value = ResearchValuation(
        identity_key="synthetic future valuation",
        company_id=1,
        forecast_run_id=run.id,
        source_valuation_id=value.source_valuation_id,
        as_of_timestamp=future,
        valuation_model_version=value.valuation_model_version,
        ntm_pe=D(99999),
        metadata_json={},
    )
    db.add(future_value)
    db.flush()
    assert build_valuation(db, run).id == value.id


def test_empirical_intervals_only_use_previously_realized_errors(db, synthetic):
    history = populate(synthetic, through=(2025, 1), count=10)
    for released, _ in history:
        run = build_forecast(db, 1, calculate_next_tradable_timestamp(released))
    q1 = stored_periods(db, run.id)[0]
    band = q1["metadata_json"]["intervals"]["revenue"]
    assert band["status"] == "empirical_P80" and band["sample_count"] == 9
    assert D(band["lower"]) <= D(band["p50"]) <= D(band["upper"])
    for sample in band["samples"]:
        assert datetime.fromisoformat(sample["actual_available_at"]) <= run.information_cutoff
        assert datetime.fromisoformat(sample["origin_as_of"]) < run.information_cutoff
    h8 = next(p for p in stored_periods(db, run.id) if p["metadata_json"].get("horizon") == 8)
    assert h8["metadata_json"]["intervals"]["revenue"]["status"] == "insufficient_history"


def test_fixed_ensemble_income_consistency_and_annual_labels(db, synthetic, tmp_path):
    released, _ = populate(synthetic, count=3)[-1]
    guide(db, tmp_path, 2024, 1, released, "revenue", "9000000")
    at = calculate_next_tradable_timestamp(released)
    outputs = {m: produce(FinancialInputs(db, 1, at), ForecastPolicyV1(m)) for m in ("A", "B", "C")}
    a, b, c = (outputs[m]["periods"][0] for m in ("A", "B", "C"))
    assert canonical(c["revenue"]) == canonical((a["revenue"] + b["revenue"]) / 2)
    assert canonical(c["gross_profit"]) == canonical((a["gross_profit"] + b["gross_profit"]) / 2)
    assert c["eps"] == c["net_income"] / c["diluted_weighted_shares"]
    rows = outputs["A"]["periods"][:4]
    assert aggregate(rows, "NTM", 2024)["eps"] == aggregate(rows, "FY1", 2025)["eps"]


def test_margin_bounds_and_forecast_loss_tax_policy_are_explicit(db, synthetic, tmp_path):
    released, _ = populate(synthetic, count=2)[-1]
    for metric, value in [
        ("gross_margin", "1.4"),
        ("operating_expenses", "99000000"),
        ("tax_rate", ".2"),
    ]:
        guide(db, tmp_path, 2024, 1, released, metric, value)
    result = produce(
        FinancialInputs(db, 1, calculate_next_tradable_timestamp(released)), ForecastPolicyV1()
    )
    q = result["periods"][0]
    assert q["gross_margin"] == 1
    assert q["pre_tax_income"] < 0 and q["net_income"] == q["pre_tax_income"] and q["tax_rate"] == 0
    reasons = {w["reason"] for w in result["metadata"]["warnings"]}
    assert "bounded" in reasons and "forecast_loss_no_tax_benefit_assumed" in reasons
