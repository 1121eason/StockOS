"""Synthetic-only formal cohort, PIT, atomic transport and frozen-arithmetic regressions."""

import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import product
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from test_confidence_contract import prepared

from valuation_engine.cadence.formal_context import load_formal_context
from valuation_engine.cadence.pipeline import CadencePipelineConfig, QuarterlyCadencePipeline
from valuation_engine.db.schema import AssumptionSet, Base, Company, ForecastRun, RegimeSnapshot
from valuation_engine.db.store import digest
from valuation_engine.decision.signal_fusion import (
    ForecastRevisionInput,
    RegimeInput,
    SignalFusionEngine,
)
from valuation_engine.regime.confidence import POLICY as CORRECTED_POLICY
from valuation_engine.regime.confidence import classify_corrected
from valuation_engine.regime.policy import REGIMES
from valuation_engine.regime.service import payload
from valuation_engine.research.numbers import POLICY, D
from valuation_engine.research.service import MODELS, policy_payload
from valuation_engine.valuation.bridge import ValuationBridgeV2

DAY = "2026-08-27"
QUARTER = "FY2027-Q2"
CHECKPOINT = datetime(2026, 8, 27, 13, 30, tzinfo=UTC)
INFORMATION = CHECKPOINT - timedelta(hours=17)


def sql_time(value):
    return value.astimezone(UTC).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")


def create_formal_database(path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            AssumptionSet.__table__,
            ForecastRun.__table__,
            RegimeSnapshot.__table__,
        ],
    )
    with Session(engine) as db:
        for number, ticker in ((1, "NVDA"), (2, "OTHER")):
            db.add(
                Company(
                    id=number,
                    ticker=ticker,
                    company_name="Synthetic",
                    cik=str(number),
                    exchange="TEST",
                    currency="USD",
                    valuation_archetype="synthetic",
                )
            )
        for number, value in (
            (1, policy_payload()),
            (2, payload(CORRECTED_POLICY)),
            (3, {"wrong": True}),
        ):
            db.add(AssumptionSet(id=number, content_hash=digest(value), assumptions=value))
        db.commit()
    engine.dispose()
    with sqlite3.connect(path) as conn:
        # Raw valuation columns intentionally permit corrupt values for the pre-existing
        # numeric/JSON guard tests. Formal identity columns match the production schema.
        conn.executescript(
            "CREATE TABLE research_valuations (id INTEGER PRIMARY KEY, company_id INTEGER, "
            "forecast_run_id INTEGER, as_of_timestamp TEXT, valuation_model_version TEXT, dcf_base, metadata_json);"
            "CREATE TABLE forecast_revisions (id INTEGER PRIMARY KEY, created_at TEXT, identity_key TEXT, previous_run_id INTEGER, forecast_run_id INTEGER, metadata_json TEXT);"
            "CREATE TABLE ai_human_reviews (verdict TEXT);"
        )


def add_cohort(
    path,
    *,
    number=1,
    at=CHECKPOINT,
    quarter=QUARTER,
    company_id=1,
    run_changes=None,
    state_changes=None,
    valuation=True,
):
    information = at - timedelta(hours=17)
    pack = prepared(1)
    pack.update(
        quarter=quarter,
        as_of=information.isoformat(),
        forecast_run_id=number,
        input_snapshot_id=number,
        feature_lineage={"synthetic_feature": ["missing_observation"]},
        input_observations={"missing_observation": {"present": False, "history_absent": True}},
    )
    pack["quality_lineage"].update(
        active_observation_ids=["missing_observation"],
        required_observations=0,
        present_observations=0,
        quality_ledger_preserved=True,
    )
    state = classify_corrected(pack, [])
    # Preserve the old fixture's scalar values while supplying the full synthetic contract.
    state["composite_confidence"] = state["confidence"] = "0.85000000"
    state.update(state_changes or {})
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as db:
        values = dict(
            id=number,
            identity_key=f"run-{number}",
            company_id=company_id,
            forecast_as_of=at,
            information_cutoff=information,
            tradable_at=at,
            forecast_type="first_tradable",
            forecast_basis="synthetic",
            generated_kind="synthetic",
            model_name=MODELS["A"],
            model_version=POLICY["version"],
            assumption_set_id=1,
            input_snapshot_id=number,
            metadata_json={"anchor": quarter},
        )
        values.update(run_changes or {})
        db.add(ForecastRun(**values))
        db.add(
            RegimeSnapshot(
                id=number,
                identity_key=f"regime-{number}",
                company_id=company_id,
                as_of_timestamp=at,
                model_version=CORRECTED_POLICY["version"],
                policy_version=CORRECTED_POLICY["version"],
                assumption_set_id=2,
                input_snapshot_id=number,
                forecast_run_id=number,
                metadata_json={
                    "inputs": pack,
                    "state": state,
                    "assumption_hash": digest(payload(CORRECTED_POLICY)),
                },
                **{
                    key: state[key]
                    for key in ("confirmed_regime", "candidate_regime", "transition_status")
                },
                **{
                    key: D(state[key])
                    for key in (
                        "evidence_confidence",
                        "data_quality_confidence",
                        "history_sufficiency",
                        "composite_confidence",
                        "candidate_probability",
                        "probability_gap_to_second_candidate",
                    )
                },
            )
        )
        db.commit()
    engine.dispose()
    if valuation:
        with sqlite3.connect(path) as conn:
            conn.execute(
                "INSERT INTO research_valuations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    number,
                    company_id,
                    number,
                    sql_time(at),
                    POLICY["valuation_version"],
                    120,
                    '{"price": 100}',
                ),
            )


@pytest.fixture
def pipeline(tmp_path):
    path = tmp_path / "synthetic-formal.db"
    create_formal_database(path)
    add_cohort(path)
    return QuarterlyCadencePipeline(
        CadencePipelineConfig(
            as_of_date=DAY, qve_db_path=path, candidate_db_path=tmp_path / "absent.db"
        )
    )


def context(pipeline):
    return load_formal_context(
        pipeline.qve_db_path,
        pipeline.config.ticker,
        QUARTER,
        pipeline.config.as_of_date,
        pipeline.config.checkpoint_timestamp,
    )


def update(path, table, column, value, *, number=1):
    with sqlite3.connect(path) as conn:
        conn.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?", (value, number))


def change_metadata(path, change):
    with sqlite3.connect(path) as conn:
        value = json.loads(
            conn.execute("SELECT metadata_json FROM regime_snapshots WHERE id=1").fetchone()[0]
        )
    change(value)
    update(path, "regime_snapshots", "metadata_json", json.dumps(value))


def assert_rejected(pipeline, match=None):
    pipeline.bridge = Mock(spec=ValuationBridgeV2)
    pipeline.fusion = Mock(spec=SignalFusionEngine)
    before = pipeline.qve_db_path.read_bytes()
    with pytest.raises(ValueError, match=match):
        pipeline.run()
    pipeline.bridge.evaluate.assert_not_called()
    pipeline.fusion.fuse_formal.assert_not_called()
    pipeline.fusion.fuse.assert_not_called()
    assert pipeline.qve_db_path.read_bytes() == before
    assert not pipeline.candidate_db_path.exists()


@pytest.mark.parametrize(
    "checkpoint", [None, CHECKPOINT, "2026-08-27T13:30:00Z", "2026-08-27T09:30:00-04:00"]
)
def test_exact_and_unique_date_only_checkpoints(pipeline, checkpoint):
    pipeline.config.checkpoint_timestamp = checkpoint
    before = pipeline.qve_db_path.read_bytes()
    result = pipeline.run()
    envelope = result.receipt_data["regime_context"]
    assert envelope == context(pipeline).regime
    assert envelope["forecast_run_id"] == envelope["snapshot_id"] == 1
    assert envelope["checkpoint_timestamp"] == CHECKPOINT.isoformat()
    assert envelope["as_of"] == INFORMATION.isoformat()
    assert envelope["quality_lineage"] == envelope["input_lineage"]["quality_lineage"]
    assert (
        envelope["input_lineage"]["input_observations"]["missing_observation"]["present"] is False
    )
    assert pipeline.qve_db_path.read_bytes() == before


@pytest.mark.parametrize(
    "checkpoint",
    ["2026-08-27T13:30:00", datetime(2026, 8, 27, 13, 30), "2026-08-27T23:30:00-04:00", "bad"],
)
def test_naive_invalid_or_conflicting_checkpoint_rejected(pipeline, checkpoint):
    pipeline.config.checkpoint_timestamp = checkpoint
    assert_rejected(pipeline)


def test_exact_checkpoint_never_falls_back_to_older_forecast(pipeline):
    pipeline.config.checkpoint_timestamp = CHECKPOINT + timedelta(minutes=1)
    assert_rejected(pipeline, "No exact formal forecast")


def test_no_date_checkpoint_rejected(pipeline):
    pipeline.config.as_of_date = "2026-08-28"
    assert_rejected(pipeline, "exactly one eligible formal checkpoint")


def test_date_only_ambiguity_requires_explicit_checkpoint(pipeline):
    add_cohort(pipeline.qve_db_path, number=2, at=CHECKPOINT + timedelta(hours=1))
    assert_rejected(pipeline, "exactly one eligible formal checkpoint")
    pipeline.config.checkpoint_timestamp = CHECKPOINT
    assert context(pipeline).regime["forecast_run_id"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"company_id": 2},
        {"metadata_json": {"anchor": "FY2027-Q1"}},
        {"information_cutoff": CHECKPOINT + timedelta(seconds=1)},
        {"tradable_at": CHECKPOINT + timedelta(seconds=1)},
        {"forecast_type": "pre_earnings"},
        {"model_name": "nonformal"},
        {"assumption_set_id": 3},
    ],
)
def test_ineligible_formal_forecast_cannot_satisfy_checkpoint(pipeline, changes):
    for field, value in changes.items():
        if isinstance(value, datetime):
            value = sql_time(value)
        elif isinstance(value, dict):
            value = json.dumps(value)
        update(pipeline.qve_db_path, "forecast_runs", field, value)
    assert_rejected(pipeline)


def test_same_checkpoint_formal_run_ambiguity_rejected(pipeline):
    add_cohort(pipeline.qve_db_path, number=2)
    assert_rejected(pipeline, "Ambiguous formal M2 forecasts")


def test_other_company_quarter_and_future_records_do_not_contaminate_selection(pipeline):
    add_cohort(pipeline.qve_db_path, number=2, company_id=2)
    add_cohort(
        pipeline.qve_db_path, number=3, quarter="FY2027-Q1", at=CHECKPOINT + timedelta(hours=1)
    )
    add_cohort(pipeline.qve_db_path, number=4, at=CHECKPOINT + timedelta(days=1))
    add_cohort(
        pipeline.qve_db_path,
        number=5,
        at=CHECKPOINT + timedelta(minutes=30),
        run_changes={"model_name": "nonformal"},
    )
    assert context(pipeline).regime["forecast_run_id"] == 1
    assert pipeline.run().quant_baseline_dcf == 120


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_id", 2),
        ("forecast_run_id", 999),
        ("as_of_timestamp", sql_time(CHECKPOINT + timedelta(seconds=1))),
        ("valuation_model_version", "legacy"),
    ],
)
def test_valuation_must_match_all_formal_identity_fields(pipeline, field, value):
    update(pipeline.qve_db_path, "research_valuations", field, value)
    assert_rejected(pipeline, "No quantitative valuation")


def test_ambiguous_valuations_rejected_even_if_values_are_identical(pipeline):
    with sqlite3.connect(pipeline.qve_db_path) as conn:
        conn.execute(
            "INSERT INTO research_valuations SELECT 2, company_id, forecast_run_id, as_of_timestamp, valuation_model_version, dcf_base, metadata_json FROM research_valuations"
        )
    assert_rejected(pipeline, "Ambiguous quantitative valuations")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company_id", 2),
        ("forecast_run_id", 999),
        ("input_snapshot_id", 999),
        ("as_of_timestamp", sql_time(CHECKPOINT + timedelta(seconds=1))),
        ("policy_version", "RegimePolicyV1"),
        ("assumption_set_id", 3),
        ("model_version", "legacy"),
        ("confirmed_regime", "Growth"),
        ("composite_confidence", "0.1"),
    ],
)
def test_snapshot_identity_and_alias_mismatch_rejected(pipeline, field, value):
    update(pipeline.qve_db_path, "regime_snapshots", field, value)
    assert_rejected(pipeline)


def test_missing_and_ambiguous_snapshots_rejected(pipeline):
    with sqlite3.connect(pipeline.qve_db_path) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(regime_snapshots)")]
        projection = ["2" if c == "id" else "'copy'" if c == "identity_key" else c for c in columns]
        conn.execute(
            f"INSERT INTO regime_snapshots SELECT {', '.join(projection)} FROM regime_snapshots"
        )
    assert_rejected(pipeline, "exactly one corrected Regime snapshot")
    with sqlite3.connect(pipeline.qve_db_path) as conn:
        conn.execute("DELETE FROM regime_snapshots")
    assert_rejected(pipeline, "exactly one corrected Regime snapshot")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("policy_version", "RegimePolicyV1"),
        ("quarter", "FY2027-Q1"),
        ("as_of", CHECKPOINT.isoformat()),
        ("as_of", "2026-08-26T20:30:00"),
    ],
)
def test_state_identity_gaps_in_snapshot_validator_are_closed(pipeline, field, value):
    change_metadata(pipeline.qve_db_path, lambda m: m["state"].update({field: value}))
    assert_rejected(pipeline)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("forecast_run_id", 99),
        ("input_snapshot_id", 99),
        ("quarter", "FY2027-Q1"),
        ("as_of", CHECKPOINT.isoformat()),
        ("quality_lineage", {}),
        ("feature_lineage", []),
        ("input_observations", []),
        ("feature_lineage", {"feature": ["nonexistent"]}),
    ],
)
def test_mixed_or_dangling_input_lineage_rejected(pipeline, field, value):
    change_metadata(pipeline.qve_db_path, lambda m: m["inputs"].update({field: value}))
    assert_rejected(pipeline)


def test_snapshot_assumption_metadata_must_agree_with_policy(pipeline):
    change_metadata(pipeline.qve_db_path, lambda m: m.update(assumption_hash="wrong"))
    assert_rejected(pipeline, "assumption hash")


def valuation():
    return ValuationBridgeV2().evaluate(
        quarter=QUARTER,
        as_of_date=DAY,
        market_price=100,
        quant_dcf_base=120,
        features={},
        challenges=[],
    )


@pytest.mark.parametrize(
    "field",
    [
        "contract_version",
        "policy_version",
        "forecast_run_id",
        "probabilities",
        "cycle_score",
        "evidence_confidence",
        "data_quality_confidence",
        "history_sufficiency",
        "composite_confidence",
        "candidate_probability",
        "probability_gap_to_second_candidate",
        "reason_codes",
        "confidence_components",
        "candidate_streak",
        "stress_streak",
        "scores",
        "structural_eligible",
        "blocked_regime",
        "input_lineage",
        "quality_lineage",
        "stress_dimensions",
    ],
)
def test_formal_fusion_rejects_incomplete_envelope(pipeline, field):
    envelope = context(pipeline).regime
    del envelope[field]
    with pytest.raises(ValueError):
        SignalFusionEngine().fuse_formal(valuation(), envelope)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contract_version", "legacy"),
        ("policy_version", "legacy"),
        ("confirmed_regime", "Unknown"),
        ("candidate_regime", "Unknown"),
        ("transition_status", "TRANSITION"),
        ("composite_confidence", "NaN"),
        ("evidence_confidence", "1.1"),
        ("data_quality_confidence", "-0.1"),
        ("candidate_probability", "0"),
        ("probability_gap_to_second_candidate", "1"),
        ("probabilities", {"Hypergrowth": "1"}),
        ("candidate_streak", -1),
        ("stress_streak", True),
        ("stress_dimensions", {"cash": True}),
        ("cycle_score", "101"),
        ("structural_eligible", "false"),
    ],
)
def test_formal_fusion_rejects_malformed_contract(pipeline, field, value):
    envelope = context(pipeline).regime
    envelope[field] = value
    with pytest.raises(ValueError):
        SignalFusionEngine().fuse_formal(valuation(), envelope)


def test_atomic_envelope_survives_fusion_json_and_caller_mutation(pipeline):
    envelope = context(pipeline).regime
    envelope.update(
        confirmed_regime="Growth",
        transition_status="STRONG_OVERRIDE_PENDING_GUARD",
        cycle_score=None,
        blocked_regime="Structural Deterioration",
        stress_streak=3,
        stress_dimensions={"growth": True, "revision": True, "margin": False, "cash": True},
    )
    before = deepcopy(envelope)
    result = SignalFusionEngine().fuse_formal(valuation(), envelope)
    assert result.regime_summary == before
    assert result.regime_summary["confirmed_regime"] != result.regime_summary["candidate_regime"]
    assert result.regime_summary["cycle_score"] is None
    assert json.loads(json.dumps(result.to_dict()))["regime_summary"] == before
    envelope["input_lineage"]["quality_lineage"]["new"] = True
    assert result.regime_summary == before


@pytest.mark.parametrize(
    ("composite", "evidence", "expected"), [("0.39", "1", 0.9), ("0.40", "0", 1.0)]
)
def test_composite_confidence_alone_controls_existing_caution_boundary(
    pipeline, composite, evidence, expected
):
    envelope = context(pipeline).regime
    envelope.update(composite_confidence=composite, evidence_confidence=evidence)
    assert SignalFusionEngine().fuse_formal(valuation(), envelope).equity_weight == expected


def test_all_formal_statuses_and_regime_caps_use_unchanged_scalar_math(pipeline):
    original = context(pipeline).regime
    engine = SignalFusionEngine()
    count = 0
    for name, status, confidence, dcf, haircut, revision in product(
        REGIMES,
        ("STABLE", "PENDING_CONFIRMATION", "LOW_CONFIDENCE", "STRONG_OVERRIDE_PENDING_GUARD"),
        ("0.39", "0.40", "0.85"),
        (60, 75, 100, 120),
        (1.0, 0.88),
        (None, -0.1, 0.1),
    ):
        envelope = deepcopy(original)
        envelope.update(
            confirmed_regime=name,
            transition_status=status,
            composite_confidence=confidence,
            blocked_regime="Structural Deterioration"
            if status == "STRONG_OVERRIDE_PENDING_GUARD"
            else None,
        )
        base = replace(
            valuation(),
            ai_expectations_gap=(dcf - 100) / 100,
            valuation_stance="FAIRLY_VALUED",
            tail_risk_haircut=haircut,
        )
        rev = (
            None
            if revision is None
            else ForecastRevisionInput(
                revision, revision, revision, "DOWNWARD" if revision < 0 else "UPWARD"
            )
        )
        formal = engine.fuse_formal(base, envelope, rev).to_dict()
        legacy = engine.fuse(
            base,
            RegimeInput(
                name,
                envelope["candidate_regime"],
                status,
                float(confidence),
                envelope["stress_dimensions"],
            ),
            rev,
        ).to_dict()
        assert formal.pop("regime_summary") == envelope
        legacy.pop("regime_summary")
        assert formal == legacy
        assert formal["equity_weight"] <= engine.REGIME_WEIGHT_CAPS[name]
        count += 1
    assert count == 1440


def test_formal_database_connection_is_enforced_read_only(pipeline, monkeypatch):
    import valuation_engine.cadence.formal_context as module

    original = module.resolve_run

    def guarded(db, *args, **kwargs):
        with pytest.raises(Exception, match="readonly"):
            db.connection().exec_driver_sql("DELETE FROM forecast_runs")
        return original(db, *args, **kwargs)

    monkeypatch.setattr(module, "resolve_run", guarded)
    before = pipeline.qve_db_path.read_bytes()
    assert pipeline.run().market_price == 100
    assert pipeline.qve_db_path.read_bytes() == before


@pytest.mark.parametrize(
    "change",
    [
        lambda e: e.update(confidence_components={}),
        lambda e: e["confidence_components"].pop("history_multiplier"),
        lambda e: e["confidence_components"].pop("forecast_sample_count"),
        lambda e: e["confidence_components"].update(history={}),
        lambda e: e["confidence_components"].update(evidence={}),
        lambda e: e.update(transition_status="STRONG_OVERRIDE_PENDING_GUARD", blocked_regime=None),
        lambda e: e.update(
            transition_status="STRONG_OVERRIDE_PENDING_GUARD",
            blocked_regime="Structural Deterioration",
            structural_eligible=True,
        ),
        lambda e: e["input_lineage"].update(feature_lineage={}, input_observations={}),
        lambda e: e.update(quality_lineage={}),
        lambda e: e["input_lineage"]["quality_lineage"].pop("required_observations"),
    ],
)
def test_incomplete_diagnostics_and_inconsistent_structural_guard_rejected(pipeline, change):
    envelope = context(pipeline).regime
    change(envelope)
    with pytest.raises(ValueError):
        SignalFusionEngine().fuse_formal(valuation(), envelope)


@pytest.mark.parametrize(
    "change",
    [
        lambda e: e.update(quarter="FY2027-Q1"),
        lambda e: e.update(checkpoint_timestamp="2026-08-28T13:30:00Z"),
    ],
)
def test_fusion_rechecks_valuation_quarter_and_checkpoint(pipeline, change):
    envelope = context(pipeline).regime
    change(envelope)
    with pytest.raises(ValueError):
        SignalFusionEngine().fuse_formal(valuation(), envelope)


def test_unknown_company_is_rejected_without_creating_one(pipeline):
    pipeline.config.ticker = "MISSING"
    assert_rejected(pipeline, "No formal company")


def test_sensitivity_policy_cohort_cannot_override_corrected_snapshot(pipeline):
    with sqlite3.connect(pipeline.qve_db_path) as conn:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(regime_snapshots)")]
        replacements = {"id": "2", "identity_key": "'sensitivity'", "assumption_set_id": "3"}
        projection = [replacements.get(column, column) for column in columns]
        conn.execute(
            f"INSERT INTO regime_snapshots SELECT {', '.join(projection)} FROM regime_snapshots"
        )
    assert context(pipeline).regime["snapshot_id"] == 1
