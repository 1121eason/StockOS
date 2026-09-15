import ast
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from test_research import populate
from test_research import synthetic as synthetic

from valuation_engine.db.schema import RegimeSnapshot, RegimeTransition
from valuation_engine.regime.features import eligible_runs, extract
from valuation_engine.regime.policy import POLICY
from valuation_engine.regime.service import replay, transitions
from valuation_engine.research.service import build_forecast
from valuation_engine.time import calculate_next_tradable_timestamp


def prepare(db, synthetic):
    releases = populate(synthetic, count=9)
    runs = [build_forecast(db, 1, calculate_next_tradable_timestamp(at)) for at, _ in releases[-5:]]
    return runs


def test_regime_replay_is_idempotent_pit_and_sequential(db, synthetic):
    runs = prepare(db, synthetic)
    cutoff = runs[-1].forecast_as_of
    rows, states, packs = replay(db, 1, cutoff)
    assert len(rows) == 5
    ids = [r.id for r in rows]
    repeated, states2, _ = replay(db, 1, cutoff.astimezone(UTC))
    assert [r.id for r in repeated] == ids
    assert states2 == states
    assert db.scalar(select(func.count()).select_from(RegimeSnapshot)) == 5
    early, _, _ = replay(db, 1, runs[1].forecast_as_of)
    assert [r.id for r in early] == ids[:2]
    for pack in packs:
        assert all(
            datetime.fromisoformat(v["available_at"].replace("Z", "+00:00")) <= cutoff
            for v in pack["financial_provenance"]["observations"].values()
        )
    for transition in transitions(db, ids):
        assert transition["effective_at"] == transition["detected_at"]
        assert transition["previous_snapshot_id"] < transition["new_snapshot_id"]
    future, _ = synthetic(2025, 1, 20, release=datetime(2024, 5, 25, 20, tzinfo=UTC))
    build_forecast(db, 1, calculate_next_tradable_timestamp(future))
    after, state_after, _ = replay(db, 1, cutoff)
    assert [r.id for r in after] == ids
    assert state_after == states


def test_regime_sql_and_imports_exclude_outcomes_prices_and_valuations(db, synthetic):
    runs = prepare(db, synthetic)
    forbidden = (
        "future_outcomes",
        "forecast_outcomes",
        "market_prices",
        "valuation_snapshots",
        "research_valuations",
        "dcf_scenarios",
        "ai_features",
    )
    statements = []

    def guard(conn, cursor, statement, parameters, context, executemany):
        assert not any(name in statement.lower() for name in forbidden), statement
        statements.append(statement)

    connection = db.connection()
    event.listen(connection, "before_cursor_execute", guard)
    try:
        replay(db, 1, runs[-1].forecast_as_of)
    finally:
        event.remove(connection, "before_cursor_execute", guard)
    assert statements
    for path in Path("src/valuation_engine/regime").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not any(
                    word in (node.module or "")
                    for word in ("evaluation", "valuation.ratios", "research.valuation", "backtest")
                )
                assert not {a.name for a in node.names}.intersection(
                    {
                        "FutureOutcome",
                        "ForecastOutcome",
                        "MarketPrice",
                        "ResearchValuation",
                        "AIFeature",
                    }
                )


def test_regime_immutable_database_guards(db, synthetic):
    runs = prepare(db, synthetic)
    rows, _, _ = replay(db, 1, runs[-1].forecast_as_of)
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(
            text("UPDATE regime_snapshots SET confidence = 0 WHERE id=:id"), {"id": rows[-1].id}
        )
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("DELETE FROM regime_snapshots WHERE id=:id"), {"id": rows[-1].id})
    # A synthetic transition tests the guard even when this smooth fixture has no actual switch.
    t = RegimeTransition(
        identity_key="test-transition",
        company_id=1,
        from_regime="Growth",
        to_regime="Mature Growth",
        effective_at=runs[-1].forecast_as_of,
        detected_at=runs[-1].forecast_as_of,
        previous_snapshot_id=rows[-2].id,
        new_snapshot_id=rows[-1].id,
        transition_strength=0,
        reason_codes=["TEST"],
        policy_version="synthetic",
    )
    if (
        db.scalar(select(RegimeTransition).where(RegimeTransition.new_snapshot_id == rows[-1].id))
        is None
    ):
        db.add(t)
        db.flush()
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(text("DELETE FROM regime_transitions WHERE id=:id"), {"id": t.id})


def test_revision_targets_and_forecast_error_leakage_guard(db, synthetic):
    runs = prepare(db, synthetic)
    p = extract(db, runs[-1], runs[:-1], POLICY)
    assert p["revision_provenance"]["trailing_4q_revision"]["consecutive"]
    assert (
        p["revision_provenance"]["trailing_4q_revision"]["same_target"]
        == p["revision_provenance"]["revision"]["same_target"]
    )
    assert p["features"]["sbc_to_revenue"] is None
    assert p["features"]["forecast_sample_count"] is not None
    assert len(eligible_runs(db, 1, runs[-1].forecast_as_of - timedelta(seconds=1))) == 4
    # Substitute an immutable forecast's serialized period at this boundary, never real data.
    import valuation_engine.regime.features as module

    old = module.stored_periods
    periods = deepcopy(old(db, runs[-1].id))
    quarter = next(r for r in periods if r["period_type"] == "quarter")
    quarter["metadata_json"]["intervals"]["revenue"]["samples"].append(
        {
            "origin_as_of": runs[-1].forecast_as_of.isoformat(),
            "actual_available_at": (runs[-1].forecast_as_of + timedelta(days=1)).isoformat(),
            "error": "1",
        }
    )
    from unittest.mock import patch

    with patch.object(
        module,
        "stored_periods",
        side_effect=lambda d, rid: periods if rid == runs[-1].id else old(d, rid),
    ):
        with pytest.raises(ValueError, match="Future forecast error"):
            extract(db, runs[-1], runs[:-1], POLICY)


@pytest.mark.parametrize("corrected", [False, True])
@pytest.mark.parametrize("factor", [4, 10])
def test_feature_ratios_and_revision_denominators_are_split_invariant(
    db, synthetic, monkeypatch, factor, corrected
):
    from valuation_engine.regime import features as module
    from valuation_engine.research.numbers import D

    runs = prepare(db, synthetic)
    from valuation_engine.regime.confidence import POLICY as NEW_POLICY
    from valuation_engine.regime.confidence import classify_corrected
    from valuation_engine.regime.lineage import extract_corrected

    extractor, policy = (extract_corrected, NEW_POLICY) if corrected else (extract, POLICY)
    baseline = extractor(db, runs[-1], runs[:-1], policy)
    original_value = module.FinancialInputs.value
    original_periods = module.stored_periods

    def value(self, quarter, metric):
        result = original_value(self, quarter, metric)
        if result is None:
            return None
        return (
            result / factor
            if metric == "eps_diluted"
            else result * factor
            if metric == "diluted_shares"
            else result
        )

    def periods(db, run_id):
        result = deepcopy(original_periods(db, run_id))
        for row in result:
            if row["eps"] is not None:
                row["eps"] /= factor
            if row["diluted_weighted_shares"] is not None:
                row["diluted_weighted_shares"] *= factor
            band = row["metadata_json"]["intervals"]["eps"]
            for key in ("lower", "upper", "base"):
                if band[key] is not None:
                    band[key] = str(D(band[key]) / factor)
        return result

    monkeypatch.setattr(module.FinancialInputs, "value", value)
    monkeypatch.setattr(module, "stored_periods", periods)
    changed = extractor(db, runs[-1], runs[:-1], policy)
    assert changed["features"] == baseline["features"]
    if corrected:
        assert classify_corrected(changed, []) == classify_corrected(baseline, [])


def test_near_zero_profit_bases_are_unavailable_not_extreme_growth(db, synthetic, monkeypatch):
    from valuation_engine.regime import features as module
    from valuation_engine.research.numbers import D

    runs = prepare(db, synthetic)
    original = module.FinancialInputs.value

    def value(self, quarter, metric):
        return (
            D("0.00000001") if metric in ("eps_diluted", "fcf") else original(self, quarter, metric)
        )

    monkeypatch.setattr(module.FinancialInputs, "value", value)
    result = extract(db, runs[-1], runs[:-1], POLICY)
    assert result["features"]["eps_yoy"] is None
    assert result["features"]["fcf_yoy"] is None
    assert any(w["feature"] == "eps_yoy" for w in result["warnings"])
