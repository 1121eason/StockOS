"""Unit tests for ValuationBridgeV1."""

import pytest
from valuation_engine.valuation.bridge import ValuationBridgeV1


def test_composite_score_empty():
    bridge = ValuationBridgeV1()
    score, groups = bridge.compute_composite_score({})
    assert score == 0.0
    assert all(v == 0.0 for v in groups.values())


def test_composite_score_weighting():
    bridge = ValuationBridgeV1()
    features = {
        "demand_momentum": (0.8, 0.9),       # growth: 0.72
        "supply_constraint": (-0.5, 0.8),     # headwinds: -0.40
        "pricing_power": (0.4, 0.7),          # moat: 0.28
        "inventory_quality": (0.2, 0.6),      # quality: 0.12
    }
    score, groups = bridge.compute_composite_score(features)
    assert groups["growth"] == 0.72
    assert groups["headwinds"] == -0.40
    assert groups["moat"] == 0.28
    assert groups["quality"] == 0.12
    # Weighted sum: 0.72*0.35 + (-0.40)*0.30 + 0.28*0.20 + 0.12*0.15 = 0.252 - 0.12 + 0.056 + 0.018 = 0.206
    assert abs(score - 0.206) < 0.001


def test_challenge_haircut():
    bridge = ValuationBridgeV1(haircut_per_downside=0.02, bonus_per_upside=0.015)
    challenges = [
        {"kind": "upside", "direction": "up"},
        {"kind": "upside", "direction": "up"},
        {"kind": "downside", "direction": "down"},
        {"kind": "anomaly", "direction": "down"},
        {"kind": "downside", "direction": "down"},
    ]
    haircut, breakdown = bridge.compute_challenge_haircut(challenges)
    assert breakdown["upsides"] == 2
    assert breakdown["downsides"] == 3
    # Net: 1.0 + 2*0.015 - 3*0.02 = 1.0 + 0.03 - 0.06 = 0.97
    assert haircut == 0.97


def test_evaluate_channels_ordering():
    bridge = ValuationBridgeV1()
    features = {
        "demand_momentum": (0.6, 0.8),
        "ecosystem_strength": (0.7, 0.9),
        "supply_constraint": (-0.4, 0.7),
    }
    challenges = [
        {"kind": "upside", "direction": "up"},
        {"kind": "downside", "direction": "down"},
    ]
    res = bridge.evaluate(
        quarter="FY2025-Q4",
        as_of_date="2025-02-27",
        market_price=135.0,
        quant_dcf_base=120.0,
        features=features,
        challenges=challenges,
    )
    assert res.ai_fair_value_stress < res.ai_fair_value_bear
    assert res.ai_fair_value_bear < res.ai_fair_value_base
    assert res.ai_fair_value_base < res.ai_fair_value_bull
    assert res.valuation_stance in ("UNDERVALUED", "FAIRLY_VALUED", "OVERVALUED")


def test_overrides_what_if():
    bridge = ValuationBridgeV1()
    features = {"demand_momentum": (0.2, 0.5)}
    base_score, _ = bridge.compute_composite_score(features)
    # What-if surge in demand
    boosted_score, _ = bridge.compute_composite_score(features, overrides={"demand_momentum": 0.9})
    assert boosted_score > base_score
