"""Offline cadence input contracts using only temporary synthetic SQLite databases."""

import json
import sqlite3
from unittest.mock import Mock

import pytest

from valuation_engine.cadence.pipeline import CadencePipelineConfig, QuarterlyCadencePipeline
from valuation_engine.decision.signal_fusion import (
    ForecastRevisionInput,
    RegimeInput,
    SignalFusionEngine,
)
from valuation_engine.valuation.bridge import ValuationBridgeV2

AS_OF = "2026-08-27"
QUARTER = "FY2027-Q2"


@pytest.fixture
def make_pipeline(tmp_path):
    def make(*, rows=(), reviews=0, revision=None, dry_run=True, require_human_review=True):
        path = tmp_path / "synthetic-qve.db"
        with sqlite3.connect(path) as conn:
            conn.executescript(
                "CREATE TABLE research_valuations "
                "(id INTEGER PRIMARY KEY, as_of_timestamp TEXT, dcf_base, metadata_json);"
                "CREATE TABLE forecast_revisions (id INTEGER PRIMARY KEY, metadata_json TEXT);"
                "CREATE TABLE ai_human_reviews (verdict TEXT);"
            )
            conn.executemany(
                "INSERT INTO research_valuations (as_of_timestamp, dcf_base, metadata_json) "
                "VALUES (?, ?, ?)",
                rows,
            )
            conn.executemany("INSERT INTO ai_human_reviews VALUES (?)", [("correct",)] * reviews)
            if revision is not None:
                conn.execute(
                    "INSERT INTO forecast_revisions (metadata_json) VALUES (?)",
                    (json.dumps(revision),),
                )
        return QuarterlyCadencePipeline(
            CadencePipelineConfig(
                as_of_date=AS_OF,
                qve_db_path=path,
                candidate_db_path=tmp_path / "synthetic-candidate.db",
                dry_run=dry_run,
                require_human_review=require_human_review,
            )
        )

    return make


def assert_invalid_before_decision(pipeline, message):
    pipeline.bridge = Mock(spec=ValuationBridgeV2)
    pipeline.fusion = Mock(spec=SignalFusionEngine)
    before = pipeline.qve_db_path.read_bytes()
    with pytest.raises(ValueError, match=message):
        pipeline.run()
    pipeline.bridge.evaluate.assert_not_called()
    pipeline.fusion.fuse.assert_not_called()
    assert pipeline.qve_db_path.read_bytes() == before
    assert not pipeline.candidate_db_path.exists()


@pytest.mark.parametrize(
    "rows",
    [(), (("2026-08-26T12:00:00+00:00", 120, '{"price": 100}'),)],
    ids=["empty", "other-date-only"],
)
def test_missing_valuation_fails_before_decision(make_pipeline, rows):
    assert_invalid_before_decision(make_pipeline(rows=rows), "No quantitative valuation")


@pytest.mark.parametrize(
    "dcf",
    [None, "", "bad", "NaN", "Infinity", "-Infinity", "1e10000", float("inf"), b"120"],
)
def test_invalid_dcf_fails_before_decision(make_pipeline, dcf):
    pipeline = make_pipeline(rows=[(AS_OF, dcf, '{"price": 100}')])
    assert_invalid_before_decision(pipeline, "dcf_base must be a finite number")


@pytest.mark.parametrize(
    "metadata",
    [None, "", "{", "null", "[]", '"text"', "42", "true"],
)
def test_invalid_metadata_fails_before_decision(make_pipeline, metadata):
    pipeline = make_pipeline(rows=[(AS_OF, 120, metadata)])
    assert_invalid_before_decision(pipeline, "metadata_json must be a JSON object")


def test_missing_price_fails_before_decision(make_pipeline):
    assert_invalid_before_decision(
        make_pipeline(rows=[(AS_OF, 120, "{}")]), "price must be a finite number"
    )


@pytest.mark.parametrize(
    "price",
    [
        None,
        "",
        "bad",
        "NaN",
        "Infinity",
        "-Infinity",
        "1e10000",
        float("nan"),
        float("inf"),
        -float("inf"),
        True,
        False,
        [],
        {},
    ],
)
def test_invalid_price_fails_before_decision(make_pipeline, price):
    pipeline = make_pipeline(rows=[(AS_OF, 120, json.dumps({"price": price}))])
    assert_invalid_before_decision(pipeline, "price must be a finite number")


@pytest.mark.parametrize("price", [0, -1, "0", "-100", "1e-10000"])
def test_nonpositive_price_fails_before_decision(make_pipeline, price):
    pipeline = make_pipeline(rows=[(AS_OF, 120, json.dumps({"price": price}))])
    assert_invalid_before_decision(pipeline, "price must be greater than zero")


def test_invalid_latest_row_does_not_fall_back_to_older_valuation(make_pipeline):
    pipeline = make_pipeline(rows=[(AS_OF, 120, '{"price": 100}'), (AS_OF, None, '{"price": 100}')])
    assert_invalid_before_decision(pipeline, "dcf_base must be a finite number")


@pytest.mark.parametrize("dcf", [0, -25, "0", "-25.50"])
def test_zero_and_negative_dcf_are_preserved(make_pipeline, dcf):
    pipeline = make_pipeline(rows=[(AS_OF, dcf, '{"price": 100}')])
    result = pipeline.run()
    expected = float(dcf)
    assert result.quant_baseline_dcf == expected
    assert result.quant_expectations_gap == (expected - 100) / 100
    assert result.receipt_data["valuation"]["quant_dcf_base"] == expected
    assert result.receipt_data["valuation"]["ai_fair_value_base"] == expected
    assert result.market_implied_growth_rate is None
    assert result.recommended_action == "CORE_ONLY"
    assert result.recommended_equity_weight == 0.4


@pytest.mark.parametrize(
    "metadata",
    [
        {"price": 100},
        {"price": 100, "reverse_dcf": None},
        {"price": 100, "reverse_dcf": {}},
        {"price": 100, "reverse_dcf": {"implied_growth": None}},
        {"price": 100, "reverse_dcf": {"status": "unavailable", "reason": "root_not_bracketed"}},
        {"price": 100, "reverse_dcf": {"status": "unavailable", "implied_growth": 0.25}},
    ],
)
def test_unavailable_reverse_dcf_stays_unavailable(make_pipeline, metadata):
    result = make_pipeline(rows=[(AS_OF, 120, json.dumps(metadata))]).run()
    assert result.market_implied_growth_rate is None
    assert result.receipt_data["valuation"]["market_implied_growth_rate"] is None
    assert not any("Reverse DCF Implied Growth" in entry for entry in result.audit_log)


@pytest.mark.parametrize("growth", [0, -0.1, 0.25, "0.25"])
def test_available_reverse_dcf_is_preserved(make_pipeline, growth):
    metadata = {"price": 100, "reverse_dcf": {"status": "converged", "implied_growth": growth}}
    result = make_pipeline(rows=[(AS_OF, 120, json.dumps(metadata))]).run()
    assert result.market_implied_growth_rate == float(growth)
    assert result.receipt_data["valuation"]["market_implied_growth_rate"] == float(growth)


@pytest.mark.parametrize("reverse_dcf", [[], "bad", False, 0])
def test_malformed_reverse_dcf_fails_before_decision(make_pipeline, reverse_dcf):
    metadata = {"price": 100, "reverse_dcf": reverse_dcf}
    pipeline = make_pipeline(rows=[(AS_OF, 120, json.dumps(metadata))])
    assert_invalid_before_decision(pipeline, "reverse_dcf must be a JSON object or null")


@pytest.mark.parametrize("growth", ["bad", "NaN", "Infinity", "-Infinity", True, [], {}])
def test_invalid_reverse_dcf_growth_fails_before_decision(make_pipeline, growth):
    metadata = {"price": 100, "reverse_dcf": {"implied_growth": growth}}
    pipeline = make_pipeline(rows=[(AS_OF, 120, json.dumps(metadata))])
    assert_invalid_before_decision(pipeline, "reverse_dcf.implied_growth must be a finite number")


@pytest.mark.parametrize(("reviews", "require_review"), [(0, True), (35, True), (0, False)])
def test_valid_baseline_preserves_existing_computations(make_pipeline, reviews, require_review):
    metadata = {"price": "200", "reverse_dcf": {"status": "converged", "implied_growth": "0.25"}}
    pipeline = make_pipeline(
        rows=[(AS_OF, "150", json.dumps(metadata))],
        reviews=reviews,
        require_human_review=require_review,
        revision={"revisions": [{"metrics": {"revenue": {"percentage_revision": "0.10"}}}]},
    )
    with sqlite3.connect(pipeline.candidate_db_path) as conn:
        conn.executescript(
            "CREATE TABLE cohort_features (quarter TEXT, feature_name TEXT, "
            "feature_value REAL, confidence REAL);"
            "CREATE TABLE cohort_challenges (quarter TEXT, kind TEXT, target_variable TEXT, "
            "direction TEXT, description TEXT);"
        )
        conn.executemany(
            "INSERT INTO cohort_features VALUES (?, ?, ?, ?)",
            [(QUARTER, "demand_momentum", 0.8, 0.9), (QUARTER, "pricing_power", 0.4, 0.8)],
        )
        conn.execute(
            "INSERT INTO cohort_challenges VALUES (?, ?, ?, ?, ?)",
            (QUARTER, "downside", "revenue", "down", "synthetic risk"),
        )
    before = (pipeline.qve_db_path.read_bytes(), pipeline.candidate_db_path.read_bytes())
    result = pipeline.run()
    downgraded = reviews == 0 and require_review
    expected_valuation = ValuationBridgeV2().evaluate(
        quarter=QUARTER,
        as_of_date=AS_OF,
        market_price=200,
        quant_dcf_base=150,
        features={} if downgraded else {"demand_momentum": (0.8, 0.9), "pricing_power": (0.4, 0.8)},
        challenges=[]
        if downgraded
        else [
            {
                "kind": "downside",
                "target_variable": "revenue",
                "direction": "down",
                "description": "synthetic risk",
            }
        ],
        market_implied_growth_rate=0.25,
        guidance_revenue_revision=0 if downgraded else 0.1,
    )
    expected_decision = SignalFusionEngine().fuse(
        expected_valuation,
        RegimeInput("Hypergrowth", "Hypergrowth", "STABLE", 0.85),
        ForecastRevisionInput(0.1, 0.1, 0.1, "UPWARD"),
    )
    assert result.market_price == 200
    assert result.quant_baseline_dcf == 150
    assert result.quant_expectations_gap == -0.25
    assert result.receipt_data["valuation"] == expected_valuation.to_dict()
    assert result.receipt_data["decision"] == expected_decision.to_dict()
    assert result.pipeline_status == (
        "SUCCESS_DOWNGRADED_QUANT_ONLY" if downgraded else "SUCCESS_APPROVED"
    )
    assert result.human_review_status == ("APPROVED" if reviews else "PENDING")
    assert result.ai_fair_value_base == (
        None if downgraded else expected_valuation.ai_fair_value_base
    )
    assert result.ai_expectations_gap == (
        None if downgraded else expected_valuation.ai_expectations_gap
    )
    assert result.recommended_action == expected_decision.action
    assert result.recommended_equity_weight == expected_decision.equity_weight
    assert result.recommended_cash_weight == expected_decision.cash_weight
    assert len(result.stages_executed) == 7
    assert result.audit_log[-1] == (
        "Stage 7: DRY-RUN complete. Execution receipt generated without database mutation."
    )
    assert before == (pipeline.qve_db_path.read_bytes(), pipeline.candidate_db_path.read_bytes())


def test_apply_mode_is_rejected_before_any_database_access(tmp_path, monkeypatch):
    pipeline = QuarterlyCadencePipeline(
        CadencePipelineConfig(
            dry_run=False,
            qve_db_path=tmp_path / "must-not-open.db",
            candidate_db_path=tmp_path / "must-not-create.db",
        )
    )
    connect = Mock(side_effect=AssertionError("Database access is forbidden"))
    monkeypatch.setattr(sqlite3, "connect", connect)
    pipeline.bridge = Mock(spec=ValuationBridgeV2)
    pipeline.fusion = Mock(spec=SignalFusionEngine)
    with pytest.raises(NotImplementedError, match="dry_run=False.*persistence is not implemented"):
        pipeline.run()
    connect.assert_not_called()
    pipeline.bridge.evaluate.assert_not_called()
    pipeline.fusion.fuse.assert_not_called()
    assert not pipeline.qve_db_path.exists()
    assert not pipeline.candidate_db_path.exists()
