from copy import deepcopy

import pytest

from valuation_engine.regime.policy import POLICY, classify, sensitivity_policies
from valuation_engine.research.numbers import D


def pack(index=1, stress=False):
    features = {
        "revenue_yoy": "-.40" if stress else ".8",
        "revenue_qoq": "-.2" if stress else ".2",
        "eps_yoy": "-.8" if stress else "1.2",
        "fcf_yoy": "-.8" if stress else "1.2",
        "fcf_growth": "-.8" if stress else "1.2",
        "growth_acceleration": "-.4" if stress else ".3",
        "gross_margin": ".15" if stress else ".75",
        "operating_margin": "-.2" if stress else ".5",
        "fcf_margin": "-.2" if stress else ".4",
        "gross_margin_change": "-.15" if stress else ".05",
        "operating_margin_change": "-.2" if stress else ".08",
        "fcf_margin_change": "-.2" if stress else ".08",
        "ar_growth": ".5" if stress else ".4",
        "inventory_growth": ".7" if stress else ".4",
        "sbc_to_revenue": ".2" if stress else ".02",
        "dso": "45",
        "capex_to_revenue": ".03",
        "operating_leverage": "1",
        "forecast_sample_count": "12",
        "forecast_error_history": "0",
        "forecast_interval_width": "0",
    }
    for prefix in ("ntm", "fy1", "fy2"):
        for metric in ("revenue", "eps"):
            features[f"{prefix}_{metric}_growth"] = "-.6" if stress else "1"
    for prefix in ("", "trailing_2q_", "trailing_4q_"):
        for metric in ("revenue", "eps", "fcf", "gross_margin", "operating_margin"):
            features[prefix + metric + "_revision"] = "-.2" if stress else ".2"
        features[prefix + "revision_breadth"] = "0" if stress else "1"
    return {
        "quarter": f"test-{index}",
        "quarter_index": index,
        "as_of": f"2024-{index:02}-01T00:00:00+00:00",
        "features": features,
        "warnings": [],
    }


def test_probability_scores_and_cycle_bounds():
    history = []
    for n in range(1, 9):
        result = classify(pack(n, n > 3), history)
        assert sum(D(x) for x in result["probabilities"].values()) == 1
        assert all(0 <= D(x) <= 1 for x in result["probabilities"].values())
        assert all(-1 <= D(x) <= 1 for x in result["scores"].values() if x is not None)
        assert -100 <= D(result["cycle_score"]) <= 100
        history.append(result)


def test_structural_requires_four_consecutive_independent_stress_quarters():
    history = []
    for n in range(1, 5):
        result = classify(pack(n, True), history)
        assert result["structural_eligible"] == (n == 4)
        if n < 4:
            assert result["primary_regime"] != "Structural Deterioration"
            assert D(result["probabilities"]["Structural Deterioration"]) == 0
        history.append(result)
    assert classify(pack(6, True), history)["stress_streak"] == 1
    assert not classify(pack(5, False), history)["structural_eligible"]


def test_inventory_anomaly_is_not_structural():
    history = []
    for n in range(1, 7):
        data = pack(n)
        data["features"]["inventory_growth"] = "99"
        state = classify(data, history)
        assert not state["structural_eligible"]
        assert state["primary_regime"] != "Structural Deterioration"
        history.append(state)


def test_hysteresis_and_strong_negative_override():
    policy = deepcopy(POLICY)
    policy["strong_transition_gap"] = "1"
    initial = classify(pack(), [], policy)
    initial["primary_regime"] = "Growth"
    initial["candidate_regime"] = "Growth"
    first = classify(pack(2), [initial], policy)
    assert first["candidate_regime"] == "Hypergrowth"
    assert first["primary_regime"] == "Growth"
    assert "PERSISTENCE_PENDING" in first["reason_codes"]
    second = classify(pack(3), [initial, first], policy)
    assert second["primary_regime"] == "Hypergrowth"
    shock = classify(pack(4, True), [initial, first, second], policy)
    assert shock["primary_regime"] == "Cyclical Downturn"
    assert "STRONG_NEGATIVE_OVERRIDE" in shock["reason_codes"]


@pytest.mark.parametrize(
    "kind",
    [
        "missing_fcf",
        "few_samples",
        "wide_interval",
        "large_errors",
        "margin_anomaly",
        "share_warning",
    ],
)
def test_quality_and_uncertainty_reduce_confidence(kind):
    data = pack()
    baseline = classify(data, [])
    changed = deepcopy(data)
    if kind == "missing_fcf":
        for key in changed["features"]:
            if "fcf" in key:
                changed["features"][key] = None
    elif kind == "few_samples":
        changed["features"]["forecast_sample_count"] = "1"
    elif kind == "wide_interval":
        changed["features"]["forecast_interval_width"] = "5"
    elif kind == "large_errors":
        changed["features"]["forecast_error_history"] = "2"
    else:
        changed["warnings"] = [
            {
                "feature": "test",
                "reason": "margin_anomaly"
                if kind == "margin_anomaly"
                else "unverified_share_basis",
            }
        ]
    result = classify(changed, [])
    assert D(result["confidence"]) < D(baseline["confidence"])
    assert max(D(v) for v in result["probabilities"].values()) < max(
        D(v) for v in baseline["probabilities"].values()
    )


def test_missing_values_remain_unavailable_and_sensitivity_is_pure():
    data = pack()
    data["features"] = {k: None for k in data["features"]}
    result = classify(data, [])
    assert all(v is None for v in result["scores"].values())
    assert result["cycle_score"] is None
    assert D(result["confidence"]) == 0
    original = deepcopy(POLICY)
    assert len(list(sensitivity_policies())) == 14
    assert POLICY == original


def test_low_confidence_quarter_breaks_confirmation_streak():
    policy = deepcopy(POLICY)
    policy["strong_transition_gap"] = "1"
    initial = classify(pack(1), [], policy)
    initial["primary_regime"] = "Growth"
    initial["candidate_regime"] = "Growth"
    low = pack(2)
    low["features"]["forecast_sample_count"] = "0"
    first = classify(low, [initial], policy)
    assert first["candidate_regime"] == "Hypergrowth"
    assert first["candidate_streak"] == 0
    second = classify(pack(3), [initial, first], policy)
    assert second["candidate_streak"] == 1
    assert second["primary_regime"] == "Growth"
    third = classify(pack(4), [initial, first, second], policy)
    assert third["primary_regime"] == "Hypergrowth"
