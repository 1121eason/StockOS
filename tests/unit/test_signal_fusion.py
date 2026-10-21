"""Offline regressions for final signal-fusion regime-cap enforcement."""

from dataclasses import replace
from itertools import product

import pytest

from valuation_engine.decision.signal_fusion import (
    ForecastRevisionInput,
    RegimeInput,
    SignalFusionEngine,
)
from valuation_engine.valuation.bridge import ValuationBridgeV2


@pytest.fixture
def valuation():
    return ValuationBridgeV2().evaluate(
        quarter="FY2025-Q1",
        as_of_date="2024-05-22",
        market_price=100.0,
        quant_dcf_base=120.0,
        features={},
        challenges=[],
    )


def make_regime(name, status="STABLE", confidence=0.90):
    return RegimeInput(
        confirmed_regime=name,
        candidate_regime=name,
        transition_status=status,
        confidence=confidence,
    )


def make_revision(direction):
    if direction is None:
        return None
    return ForecastRevisionInput(
        revenue_revision_pct=0.10 if direction == "UPWARD" else -0.10,
        eps_revision_pct=0.0,
        fcf_revision_pct=0.0,
        revision_direction=direction,
    )


@pytest.mark.parametrize(
    ("regime_name", "status", "confidence", "revision", "haircut", "expected"),
    [
        pytest.param(
            "Cyclical Downturn", "STABLE", 0.90, "UPWARD", 1.0, 0.40, id="downturn-upward"
        ),
        pytest.param(
            "Structural Deterioration",
            "TRANSITION",
            0.90,
            None,
            1.0,
            0.0,
            id="structural-transition",
        ),
        pytest.param(
            "Structural Deterioration", "VOLATILE", 0.90, None, 1.0, 0.0, id="structural-volatile"
        ),
        pytest.param(
            "Structural Deterioration",
            "STABLE",
            0.39,
            None,
            1.0,
            0.0,
            id="structural-low-confidence",
        ),
        pytest.param(
            "Structural Deterioration",
            "STABLE",
            0.90,
            "DOWNWARD",
            1.0,
            0.0,
            id="structural-downward",
        ),
        pytest.param(
            "Structural Deterioration", "STABLE", 0.90, "UPWARD", 1.0, 0.0, id="structural-upward"
        ),
        pytest.param(
            "Structural Deterioration", "STABLE", 0.90, None, 0.88, 0.0, id="structural-tail-risk"
        ),
        pytest.param(
            "Structural Deterioration",
            "VOLATILE",
            0.20,
            "DOWNWARD",
            0.88,
            0.0,
            id="structural-combined",
        ),
        pytest.param(
            "Mature Growth", "STABLE", 0.90, "UPWARD", 1.0, 0.85, id="mature-growth-upward"
        ),
    ],
)
def test_regime_caps_remain_hard_after_late_adjustments(
    valuation, regime_name, status, confidence, revision, haircut, expected
):
    result = SignalFusionEngine().fuse(
        replace(valuation, tail_risk_haircut=haircut),
        make_regime(regime_name, status, confidence),
        make_revision(revision),
    )

    assert result.equity_weight == expected
    assert result.equity_weight <= SignalFusionEngine.REGIME_WEIGHT_CAPS[regime_name]
    assert result.cash_weight == round(1.0 - expected, 2)
    assert result.equity_weight + result.cash_weight == pytest.approx(1.0)
    assert (
        result.action
        == {
            0.0: "CAPITAL_PRESERVATION",
            0.40: "CORE_ONLY",
            0.85: "OVERWEIGHT",
        }[expected]
    )


@pytest.mark.parametrize(
    ("regime_name", "status", "revision", "before", "after", "reduction"),
    [
        ("Cyclical Downturn", "STABLE", "UPWARD", 50, 40, 10),
        ("Structural Deterioration", "VOLATILE", None, 20, 0, 20),
        ("Mature Growth", "STABLE", "UPWARD", 95, 85, 10),
    ],
)
def test_final_regime_guard_audits_actual_cap_reduction(
    valuation, regime_name, status, revision, before, after, reduction
):
    result = SignalFusionEngine().fuse(
        valuation, make_regime(regime_name, status), make_revision(revision)
    )

    assert result.audit_trail[-1] == (
        f"Final Regime Guard: Confirmed regime '{regime_name}' caps post-adjustment equity "
        f"from {before}% to {after}% (reduction of {reduction} percentage points)."
    )


@pytest.mark.parametrize(
    ("regime_name", "status", "revision", "haircut", "weight", "adjustments"),
    [
        ("Hypergrowth", "STABLE", "UPWARD", 1.0, 1.0, (0.0, 0.0, 0.0)),
        ("Growth", "VOLATILE", "UPWARD", 1.0, 1.0, (-0.10, 0.10, 0.0)),
        ("Mature Growth", "STABLE", "DOWNWARD", 1.0, 0.70, (-0.15, -0.15, 0.0)),
        ("Cyclical Downturn", "STABLE", "DOWNWARD", 1.0, 0.25, (-0.60, -0.15, 0.0)),
        ("Cyclical Downturn", "STABLE", None, 0.88, 0.30, (-0.60, 0.0, -0.10)),
        ("Cyclical Downturn", "STABLE", "UPWARD", 0.88, 0.40, (-0.60, 0.10, -0.10)),
        ("Cyclical Downturn", "VOLATILE", "DOWNWARD", 0.88, 0.20, (-0.70, -0.15, -0.10)),
        ("Structural Deterioration", "STABLE", None, 1.0, 0.0, (-1.0, 0.0, 0.0)),
        ("Unknown", "STABLE", "UPWARD", 1.0, 1.0, (0.0, 0.0, 0.0)),
    ],
)
def test_unbound_allocations_and_nominal_adjustments_are_unchanged(
    valuation, regime_name, status, revision, haircut, weight, adjustments
):
    result = SignalFusionEngine().fuse(
        replace(valuation, tail_risk_haircut=haircut),
        make_regime(regime_name, status),
        make_revision(revision),
    )

    assert result.equity_weight == weight
    assert result.cash_weight == round(1.0 - weight, 2)
    assert (
        result.regime_adjustment,
        result.revision_adjustment,
        result.tail_risk_adjustment,
    ) == adjustments
    assert not any(log.startswith("Final Regime Guard:") for log in result.audit_trail)


def test_cap_guard_preserves_nominal_pillar_adjustments(valuation):
    result = SignalFusionEngine().fuse(
        valuation,
        make_regime("Structural Deterioration", "VOLATILE"),
        make_revision("DOWNWARD"),
    )

    # Existing fields describe requested pillar adjustments, not realized deltas
    # after floors and the final hard cap. The guard's actual effect is audited.
    assert result.regime_adjustment == -1.10
    assert result.revision_adjustment == -0.15
    assert result.tail_risk_adjustment == 0.0
    assert result.equity_weight == 0.0
    assert "reduction of 20 percentage points" in result.audit_trail[-1]


def test_regime_cap_and_cash_invariants_across_signal_combinations(valuation):
    engine = SignalFusionEngine()
    regimes = [None, "Unknown", *engine.REGIME_WEIGHT_CAPS]
    for name, status, confidence, gap, revision, haircut in product(
        regimes,
        ["STABLE", "TRANSITION", "VOLATILE"],
        [0.39, 0.40],
        [-0.35, -0.20, -0.15, 0.05],
        [None, "UPWARD", "DOWNWARD", "NEUTRAL"],
        [0.88, 0.90],
    ):
        result = engine.fuse(
            replace(
                valuation,
                ai_expectations_gap=gap,
                valuation_stance="FAIR_VALUE",
                tail_risk_haircut=haircut,
            ),
            make_regime(name, status, confidence) if name else None,
            make_revision(revision),
        )
        case = (name, status, confidence, gap, revision, haircut)
        assert 0.0 <= result.equity_weight <= engine.REGIME_WEIGHT_CAPS.get(name, 1.0), case
        assert 0.0 <= result.cash_weight <= 1.0, case
        assert result.equity_weight + result.cash_weight == pytest.approx(1.0), case
