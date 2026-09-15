from copy import deepcopy

from test_regime_policy import pack

from valuation_engine.regime.confidence import POLICY, classify_corrected, output_contract
from valuation_engine.research.numbers import D


def prepared(index, stress=False):
    value = pack(index, stress)
    value["quality_lineage"] = {
        "active_penalties": [],
        "excluded_warnings": [],
        "observation_completeness": "1",
        "rolling_history_coverage": "1",
    }
    value["revision_provenance"] = {
        prefix + "revision": {"consecutive": True, "previous_label": "FY1"}
        for prefix in ("", "trailing_2q_", "trailing_4q_")
    }
    return value


def test_pending_low_quality_reset_and_full_envelope():
    policy = deepcopy(POLICY)
    policy["strong_transition_gap"] = "1"
    first = classify_corrected(prepared(1), [], policy)
    first["primary_regime"] = first["confirmed_regime"] = "Growth"
    first["candidate_regime"] = "Growth"
    second = classify_corrected(prepared(2), [first], policy)
    assert second["candidate_regime"] == "Hypergrowth"
    assert second["confirmed_regime"] == "Growth"
    assert second["transition_status"] == "PENDING_CONFIRMATION"
    low = prepared(3)
    low["quality_lineage"]["observation_completeness"] = ".1"
    third = classify_corrected(low, [first, second], policy)
    assert third["transition_status"] == "LOW_CONFIDENCE" and third["candidate_streak"] == 0
    fourth = classify_corrected(prepared(4), [first, second, third], policy)
    assert fourth["candidate_streak"] == 1 and fourth["confirmed_regime"] == "Growth"
    fifth = classify_corrected(prepared(5), [first, second, third, fourth], policy)
    assert fifth["confirmed_regime"] == "Hypergrowth" and fifth["transition_status"] == "STABLE"
    contract = output_contract(fifth, 123)
    assert sum(D(x) for x in contract["probabilities"].values()) == 1
    assert D(contract["probability_gap_to_second_candidate"]) >= 0


def test_structural_guard_and_evidence_are_not_data_quality():
    states = []
    for n in range(1, 5):
        state = classify_corrected(prepared(n, True), states)
        assert state["structural_eligible"] == (n == 4)
        if n < 4:
            assert state["confirmed_regime"] != "Structural Deterioration"
        states.append(state)
    assert states[-1]["confirmed_regime"] == "Structural Deterioration"
    high = prepared(6)
    low = deepcopy(high)
    low["features"]["forecast_sample_count"] = "0"
    a, b = classify_corrected(high, []), classify_corrected(low, [])
    assert a["evidence_confidence"] == b["evidence_confidence"]
    assert a["data_quality_confidence"] == b["data_quality_confidence"]
    assert D(a["history_sufficiency"]) > D(b["history_sufficiency"])
    assert D(a["composite_confidence"]) > D(b["composite_confidence"])


def test_contract_rejects_mixed_probability_evidence():
    import pytest

    state = classify_corrected(prepared(1), [])
    mixed = deepcopy(state)
    mixed["candidate_probability"] = "0"
    with pytest.raises(ValueError, match="does not match"):
        output_contract(mixed, 1)
