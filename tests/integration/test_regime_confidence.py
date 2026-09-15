from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event
from test_regime import prepare
from test_research import synthetic as synthetic

from valuation_engine.db.schema import DataQualityIssue, MarketPrice
from valuation_engine.regime.confidence import POLICY, classify_corrected, output_contract
from valuation_engine.regime.lineage import attach_quality, extract_corrected
from valuation_engine.regime.policy import POLICY as ORIGINAL
from valuation_engine.regime.service import replay
from valuation_engine.research.numbers import D
from valuation_engine.research.service import build_forecast
from valuation_engine.time import calculate_next_tradable_timestamp


def test_original_core_parameters_unchanged():
    assert all(POLICY[key] == value for key, value in ORIGINAL.items() if key != "version")
    assert POLICY["version"] != ORIGINAL["version"]


def test_relevant_warning_and_irrelevant_historical_warning(db, synthetic):
    runs = prepare(db, synthetic)
    pack = extract_corrected(db, runs[-1], runs[:-1], POLICY)
    baseline = classify_corrected(pack, [])
    relevant = {"parameter": pack["quarter"] + ":eps_diluted", "reason": "unverified_share_basis"}
    changed = attach_quality(deepcopy(pack), pack["warnings"] + [relevant])
    affected = classify_corrected(changed, [])
    assert D(affected["data_quality_confidence"]) < D(baseline["data_quality_confidence"])
    assert affected["evidence_confidence"] == baseline["evidence_confidence"]
    assert affected["scores"] == baseline["scores"]
    assert changed["quality_lineage"]["active_penalties"]
    assert all(
        p["feature_names"] and p["observation_ids"]
        for p in changed["quality_lineage"]["active_penalties"]
    )
    # Same period can be active for revenue seasonality without its EPS being used.
    oldest = next(
        o["period"]
        for o in pack["input_observations"].values()
        if o.get("metric_name") == "revenue" and o.get("lag", 0) >= 7
    )
    stale = {"parameter": oldest + ":eps_diluted", "reason": "unverified_share_basis"}
    clean = attach_quality(deepcopy(pack), pack["warnings"] + [stale])
    unaffected = classify_corrected(clean, [])
    assert unaffected["data_quality_confidence"] == baseline["data_quality_confidence"]
    assert unaffected["composite_confidence"] == baseline["composite_confidence"]
    assert any(w["warning"] == stale for w in clean["quality_lineage"]["excluded_warnings"])


def test_pit_quality_registry_and_future_issue_isolation(db, synthetic):
    runs = prepare(db, synthetic)
    cutoff = runs[-1].information_cutoff
    before = extract_corrected(db, runs[-1], runs[:-1], POLICY)
    key = "actual:" + before["quarter"] + ":revenue"
    obs = before["input_observations"][key]
    issue = DataQualityIssue(
        identity_key="synthetic-quality",
        company_id=1,
        source_document_id=obs["source_document_ids"][0],
        issue_type="source_parse_uncertainty",
        severity="warning",
        metric_name="revenue",
        fiscal_period=before["quarter"],
        details={"fact_ids": obs["fact_ids"]},
        created_at=cutoff,
    )
    db.add(issue)
    db.flush()
    after = extract_corrected(db, runs[-1], runs[:-1], POLICY)
    assert D(classify_corrected(after, [])["data_quality_confidence"]) < D(
        classify_corrected(before, [])["data_quality_confidence"]
    )
    db.add(
        DataQualityIssue(
            identity_key="future-quality",
            company_id=1,
            source_document_id=issue.source_document_id,
            issue_type="future_review",
            severity="warning",
            metric_name="revenue",
            fiscal_period=before["quarter"],
            details=issue.details,
            created_at=cutoff + timedelta(days=1),
        )
    )
    db.flush()
    assert extract_corrected(db, runs[-1], runs[:-1], POLICY) == after


def test_corrected_persistence_contract_is_immutable_and_price_independent(db, synthetic):
    runs = prepare(db, synthetic)
    cutoff = runs[-1].forecast_as_of
    records, states, packs = replay(db, 1, cutoff, POLICY)
    ids = [r.id for r in records]
    for row, state in zip(records, states, strict=True):
        assert row.confirmed_regime == state["confirmed_regime"] == row.primary_regime
        assert row.candidate_regime == state["candidate_regime"]
        assert row.evidence_confidence == D(state["evidence_confidence"])
        assert row.data_quality_confidence == D(state["data_quality_confidence"])
        assert row.transition_status == state["transition_status"]
        assert (
            output_contract(state, row.forecast_run_id)["probabilities"] == state["probabilities"]
        )
    with pytest.raises(ValueError, match="confirmed-only"):
        output_contract({"confirmed_regime": "Growth"}, runs[-1].id)
    db.add(
        MarketPrice(
            company_id=1,
            ticker="NVDA",
            timestamp=cutoff,
            available_at=cutoff,
            price_type="synthetic",
            open=999999,
            high=999999,
            low=999999,
            close=999999,
            volume=1,
            currency="USD",
            provider="synthetic",
            retrieved_at=cutoff,
            content_hash="price-shock",
        )
    )
    db.flush()
    forbidden = (
        "market_prices",
        "future_outcomes",
        "forecast_outcomes",
        "research_valuations",
        "valuation_snapshots",
        "ai_features",
    )

    def guard(conn, cursor, statement, parameters, context, executemany):
        assert not any(word in statement.lower() for word in forbidden), statement

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", guard)
    try:
        repeated, again, _ = replay(db, 1, cutoff, POLICY)
    finally:
        event.remove(connection, "before_cursor_execute", guard)
    assert [r.id for r in repeated] == ids and again == states
    future, _ = synthetic(2025, 1, 20, release=datetime(2024, 5, 25, 20, tzinfo=UTC))
    build_forecast(db, 1, calculate_next_tradable_timestamp(future))
    repeated, again, _ = replay(db, 1, cutoff, POLICY)
    assert [r.id for r in repeated] == ids and again == states
    # Legacy M3 remains a distinct cohort and is neither backfilled nor overwritten.
    old, old_states, _ = replay(db, 1, cutoff, ORIGINAL)
    assert set(ids).isdisjoint(r.id for r in old)
    assert all(r.confirmed_regime is None for r in old)
    assert all("evidence_confidence" not in s for s in old_states)


def test_economic_margin_warning_does_not_claim_measurement_error(db, synthetic):
    runs = prepare(db, synthetic)
    pack = extract_corrected(db, runs[-1], runs[:-1], POLICY)
    baseline = classify_corrected(pack, [])
    changed = attach_quality(
        deepcopy(pack), pack["warnings"] + [{"feature": "fcf_margin", "reason": "margin_anomaly"}]
    )
    assert (
        classify_corrected(changed, [])["data_quality_confidence"]
        == baseline["data_quality_confidence"]
    )
    assert any(
        w["exclusion_reason"] == "economic_signal_not_measurement_reliability"
        for w in changed["quality_lineage"]["excluded_warnings"]
    )
