"""Exact-run, signed same-target revision and fail-closed cadence regressions."""

import json
import sqlite3
from copy import deepcopy
from datetime import timedelta
from unittest.mock import Mock

import pytest
from test_cadence_formal_regime import CHECKPOINT, DAY, add_cohort, create_formal_database

from valuation_engine.cadence.pipeline import CadencePipelineConfig, QuarterlyCadencePipeline
from valuation_engine.db.store import digest
from valuation_engine.decision.signal_fusion import SignalFusionEngine
from valuation_engine.valuation.bridge import ValuationBridgeV2


def add_revision(path, *, values=(-0.10, 0.20, -0.30), target="FY2027", number=1):
    add_cohort(
        path, number=100, at=CHECKPOINT - timedelta(days=90), quarter="FY2027-Q1", valuation=False
    )
    metadata = {
        "status": "available",
        "previous_run_id": 100,
        "forecast_run_id": 1,
        "split_factor": "1",
        "comparisons": [
            {
                "target": target,
                "previous_label": "FY2" if "-Q" not in target else "quarter",
                "new_label": "FY1" if "-Q" not in target else "quarter",
                "metrics": {
                    name: {"percentage_revision": value}
                    for name, value in zip(
                        ("revenue", "eps", "free_cash_flow"), values, strict=True
                    )
                },
            }
        ],
    }
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO forecast_revisions (id, identity_key, previous_run_id, forecast_run_id, metadata_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                number,
                digest(["run-100", "run-1", "ForecastRevisionV1"]),
                100,
                1,
                json.dumps(metadata),
            ),
        )
    return metadata


@pytest.fixture
def pipeline(tmp_path):
    path = tmp_path / "formal.db"
    create_formal_database(path)
    add_cohort(path)
    return QuarterlyCadencePipeline(
        CadencePipelineConfig(
            as_of_date=DAY,
            qve_db_path=path,
            candidate_db_path=tmp_path / "candidate.db",
            revision_target="FY2027",
        )
    )


def replace_metadata(pipeline, metadata):
    with sqlite3.connect(pipeline.qve_db_path) as conn:
        conn.execute(
            "UPDATE forecast_revisions SET metadata_json=? WHERE id=1", (json.dumps(metadata),)
        )


def assert_withheld(pipeline, reason):
    pipeline.fusion = Mock(spec=SignalFusionEngine)
    before = pipeline.qve_db_path.read_bytes()
    result = pipeline.run()
    assert result.pipeline_status == "INCOMPLETE_REVISION_CONTEXT"
    assert result.recommended_action is None
    assert result.recommended_equity_weight is None
    assert result.recommended_cash_weight is None
    assert result.receipt_data["decision"] is None
    assert result.receipt_data["forecast_revision"]["reason"] == reason
    pipeline.fusion.fuse_formal.assert_not_called()
    assert before == pipeline.qve_db_path.read_bytes()
    return result


def assert_rejected(pipeline, match):
    pipeline.bridge = Mock(spec=ValuationBridgeV2)
    pipeline.fusion = Mock(spec=SignalFusionEngine)
    before = pipeline.qve_db_path.read_bytes()
    with pytest.raises(ValueError, match=match):
        pipeline.run()
    pipeline.bridge.evaluate.assert_not_called()
    pipeline.fusion.fuse_formal.assert_not_called()
    assert before == pipeline.qve_db_path.read_bytes()


def test_explicit_target_preserves_distinct_signed_metrics_and_roll_labels(pipeline):
    add_revision(pipeline.qve_db_path)
    before = pipeline.qve_db_path.read_bytes()
    result = pipeline.run()
    revision = result.receipt_data["forecast_revision"]
    assert revision["status"] == "AVAILABLE"
    assert revision["previous_label"] == "FY2"
    assert revision["new_label"] == "FY1"
    assert revision["forecast_run_id"] == 1
    assert revision["previous_run_id"] == 100
    assert revision["metrics"] == {"revenue": -0.1, "eps": 0.2, "free_cash_flow": -0.3}
    assert result.receipt_data["decision"]["revision_summary"] == {
        "revenue_revision_pct": -0.1,
        "eps_revision_pct": 0.2,
        "fcf_revision_pct": -0.3,
        "revision_direction": "DOWNWARD",
    }
    assert result.receipt_data["decision"]["revision_adjustment"] == -0.15
    assert before == pipeline.qve_db_path.read_bytes()


@pytest.mark.parametrize(
    "revenue,direction,adjustment",
    [
        (-0.03, "NEUTRAL", 0),
        (-0.01, "NEUTRAL", 0),
        (0, "NEUTRAL", 0),
        (0.05, "NEUTRAL", 0),
        (0.06, "UPWARD", 0),
    ],
)
def test_existing_revision_boundaries_unchanged(pipeline, revenue, direction, adjustment):
    add_revision(pipeline.qve_db_path, values=(revenue, 0, 0))
    decision = pipeline.run().receipt_data["decision"]
    assert decision["revision_summary"]["revision_direction"] == direction
    assert decision["revision_adjustment"] == adjustment


def test_zero_revision_is_available_only_when_explicitly_stored(pipeline):
    add_revision(pipeline.qve_db_path, values=(0, 0, 0))
    assert pipeline.run().receipt_data["forecast_revision"]["status"] == "AVAILABLE"


def test_missing_target_never_becomes_zero_signal(pipeline):
    pipeline.config.revision_target = None
    assert_withheld(pipeline, "fiscal_target_not_selected")


def test_missing_revision_never_becomes_zero_signal(pipeline):
    assert_withheld(pipeline, "exact_run_revision_not_stored")


def test_missing_comparison_is_not_another_horizon(pipeline):
    add_revision(pipeline.qve_db_path, target="FY2028")
    assert_withheld(pipeline, "selected_fiscal_target_not_available")


@pytest.mark.parametrize("missing", [0, 1, 2])
def test_unavailable_metric_is_preserved_and_withholds_decision(pipeline, missing):
    values = [-0.1, 0.2, -0.3]
    values[missing] = None
    add_revision(pipeline.qve_db_path, values=values)
    result = assert_withheld(pipeline, "missing_revision_metrics")
    metrics = result.receipt_data["forecast_revision"]["metrics"]
    assert list(metrics.values()) == values
    assert result.receipt_data["forecast_revision"]["status"] == "INCOMPLETE"


@pytest.mark.parametrize(
    "target", ["FY1", "NTM", "FY2027-Q0", "FY2027-Q5", "2027", "FY2027 ", "", True]
)
def test_implicit_or_invalid_horizons_rejected(pipeline, target):
    pipeline.config.revision_target = target
    assert_rejected(pipeline, "revision_target")


@pytest.mark.parametrize("value", ["NaN", "inf", "-inf", "1e9999", True, False, [], {}, "invalid"])
@pytest.mark.parametrize("metric", ["revenue", "eps", "free_cash_flow"])
def test_invalid_metrics_fail_before_fusion(pipeline, value, metric):
    metadata = add_revision(pipeline.qve_db_path)
    metadata["comparisons"][0]["metrics"][metric]["percentage_revision"] = value
    replace_metadata(pipeline, metadata)
    assert_rejected(pipeline, "finite number")


def test_global_latest_other_run_and_future_revision_ignored(pipeline):
    add_revision(pipeline.qve_db_path)
    with sqlite3.connect(pipeline.qve_db_path) as conn:
        conn.execute(
            "INSERT INTO forecast_revisions (id, forecast_run_id, metadata_json) VALUES (999, 999, 'invalid')"
        )
    assert pipeline.run().receipt_data["forecast_revision"]["revision_id"] == 1


def test_other_target_larger_upside_never_replaces_selected_negative(pipeline):
    metadata = add_revision(pipeline.qve_db_path)
    other = deepcopy(metadata["comparisons"][0])
    other.update(target="FY2028", new_label="FY2")
    other["metrics"]["revenue"]["percentage_revision"] = 10.0
    metadata["comparisons"].append(other)
    replace_metadata(pipeline, metadata)
    assert pipeline.run().receipt_data["forecast_revision"]["metrics"]["revenue"] == -0.1


@pytest.mark.parametrize(
    "field,value",
    [
        ("forecast_run_id", 999),
        ("previous_run_id", 999),
        ("forecast_run_id", True),
        ("split_factor", 0),
        ("split_factor", None),
        ("status", "unavailable"),
        ("comparisons", {}),
    ],
)
def test_payload_contract_corruption_rejected(pipeline, field, value):
    metadata = add_revision(pipeline.qve_db_path)
    metadata[field] = value
    replace_metadata(pipeline, metadata)
    assert_rejected(pipeline, "Revision")


def test_legacy_wrong_payload_key_rejected(pipeline):
    metadata = add_revision(pipeline.qve_db_path)
    metadata["revisions"] = metadata.pop("comparisons")
    replace_metadata(pipeline, metadata)
    assert_rejected(pipeline, "comparisons")


def test_duplicate_selected_comparison_rejected(pipeline):
    metadata = add_revision(pipeline.qve_db_path)
    metadata["comparisons"] *= 2
    replace_metadata(pipeline, metadata)
    assert_rejected(pipeline, "Ambiguous comparisons")


def test_duplicate_run_revision_rejected(pipeline):
    add_revision(pipeline.qve_db_path)
    with sqlite3.connect(pipeline.qve_db_path) as conn:
        conn.execute("INSERT INTO forecast_revisions (id, forecast_run_id) VALUES (2, 1)")
    assert_rejected(pipeline, "Ambiguous revisions")


@pytest.mark.parametrize(
    "field,value",
    [
        ("company_id", 2),
        ("forecast_type", "pre_earnings"),
        ("model_name", "other"),
        ("assumption_set_id", 3),
        ("forecast_as_of", "2026-08-28 13:30:00"),
        ("information_cutoff", "2026-08-28 13:30:00"),
    ],
)
def test_cross_company_policy_or_future_predecessor_rejected(pipeline, field, value):
    add_revision(pipeline.qve_db_path)
    with sqlite3.connect(pipeline.qve_db_path) as conn:
        conn.execute(f"UPDATE forecast_runs SET {field}=? WHERE id=100", (value,))
    assert_rejected(pipeline, "predecessor")


def test_stale_previous_run_is_not_fallback(pipeline):
    add_revision(pipeline.qve_db_path)
    add_cohort(
        pipeline.qve_db_path,
        number=101,
        at=CHECKPOINT - timedelta(days=80),
        quarter="FY2027-Q1",
        valuation=False,
    )
    assert_rejected(pipeline, "predecessor")


def test_bad_revision_identity_rejected(pipeline):
    add_revision(pipeline.qve_db_path)
    with sqlite3.connect(pipeline.qve_db_path) as conn:
        conn.execute("UPDATE forecast_revisions SET identity_key='other'")
    assert_rejected(pipeline, "identity")


@pytest.mark.parametrize("require_review", [True, False])
def test_arbitrary_candidate_and_global_positive_reviews_cannot_enable_ai(pipeline, require_review):
    add_revision(pipeline.qve_db_path)
    pipeline.config.require_human_review = require_review
    pipeline.candidate_db_path.write_bytes(b"Not even a database; legacy inputs must not be opened")
    with sqlite3.connect(pipeline.qve_db_path) as conn:
        conn.executemany("INSERT INTO ai_human_reviews VALUES (?)", [("correct",)] * 100)
    before = pipeline.candidate_db_path.read_bytes()
    result = pipeline.run()
    assert result.human_review_status == "PENDING"
    assert result.pipeline_status == "SUCCESS_DOWNGRADED_QUANT_ONLY"
    assert result.ai_fair_value_base is None
    assert result.receipt_data["valuation"]["ai_composite_score"] == 0
    assert result.receipt_data["valuation"]["tail_risk_haircut"] == 1
    assert result.receipt_data["human_review"]["ai_inputs_admitted"] is False
    assert pipeline.candidate_db_path.read_bytes() == before


@pytest.mark.parametrize("field", ["previous_label", "new_label"])
@pytest.mark.parametrize("value", [[], {}, None, True, "NTM", "quarter"])
def test_invalid_annual_labels_raise_value_error(pipeline, field, value):
    metadata = add_revision(pipeline.qve_db_path)
    metadata["comparisons"][0][field] = value
    replace_metadata(pipeline, metadata)
    assert_rejected(pipeline, "Revision labels")


def test_explicit_quarter_target_preserves_quarter_identity(pipeline):
    pipeline.config.revision_target = "FY2027-Q3"
    add_revision(pipeline.qve_db_path, target="FY2027-Q3")
    revision = pipeline.run().receipt_data["forecast_revision"]
    assert revision["status"] == "AVAILABLE"
    assert revision["target"] == "FY2027-Q3"
    assert revision["previous_label"] == revision["new_label"] == "quarter"


@pytest.mark.parametrize("revenue,adjustment", [(0.0799, 0), (0.08, 0.1)])
def test_existing_eight_percent_bonus_boundary_with_eligible_valuation(
    pipeline, revenue, adjustment
):
    add_revision(pipeline.qve_db_path, values=(revenue, 0, 0))
    with sqlite3.connect(pipeline.qve_db_path) as conn:
        conn.execute("UPDATE research_valuations SET dcf_base=90 WHERE forecast_run_id=1")
    decision = pipeline.run().receipt_data["decision"]
    assert decision["revision_adjustment"] == adjustment
