"""Explicit independent confidence concepts; no price, return or evaluation input."""

import json
from pathlib import Path

from valuation_engine.regime.policy import LAYERS, REGIMES, classify, weighted
from valuation_engine.research.numbers import D, canonical, mean

POLICY = json.loads(Path(__file__).with_name("policy_v1_1.json").read_text())
INDEPENDENT = ("growth", "revision", "profitability", "cash_quality")


def confidence_components(pack, scores, strengths, policy):
    def p(key):
        return D(str(policy[key]))

    ordered = sorted(policy["tie_order"], key=lambda r: strengths[r], reverse=True)
    candidate, second = ordered[:2]
    raw = {r: strengths[r] / sum(strengths.values()) for r in REGIMES}
    proto = dict(zip(LAYERS, policy["prototypes"][candidate], strict=True))
    runner = dict(zip(LAYERS, policy["prototypes"][second], strict=True))
    residuals = {k: (v - D(proto[k])) ** 2 if v is not None else None for k, v in scores.items()}
    distance = weighted(residuals, policy["layer_weights"])
    variance = weighted(
        {
            k: (v - distance) ** 2 if v is not None and distance is not None else None
            for k, v in residuals.items()
        },
        policy["layer_weights"],
    )
    support = []
    for key in INDEPENDENT:
        if scores[key] is None:
            support.append(D(0))
        else:
            a, b = abs(scores[key] - D(proto[key])), abs(scores[key] - D(runner[key]))
            support.append(D(1) if a < b else D("0.5") if a == b else D(0))
    parts = {
        "candidate_probability": raw[candidate],
        "separation": (strengths[candidate] - strengths[second])
        / (strengths[candidate] + strengths[second]),
        "support_breadth": mean(support),
        "score_consistency": 1 / (1 + variance / p("prototype_temperature"))
        if variance is not None
        else D(0),
        "evidence_strength": 1 / (1 + distance / p("prototype_temperature"))
        if distance is not None
        else D(0),
    }
    evidence = weighted(parts, policy["evidence_component_weights"])
    q = pack["quality_lineage"]
    penalty = sum(
        p("share_warning_quality_penalty")
        if w["penalty_kind"] == "share_basis"
        else p("quality_issue_penalty")
        for w in q["active_penalties"]
    )
    penalty = min(p("maximum_anomaly_quality_penalty"), penalty)
    quality = D(q["observation_completeness"]) * (1 - penalty)
    samples = D(pack["features"]["forecast_sample_count"] or 0)
    revision_coverage = (
        D(
            sum(
                pack["revision_provenance"][prefix + "revision"]["consecutive"]
                and pack["revision_provenance"][prefix + "revision"]["previous_label"] is not None
                for prefix in ("", "trailing_2q_", "trailing_4q_")
            )
        )
        / 3
    )
    history_parts = {
        "forecast_error_samples": min(D(1), samples / p("confidence_full_samples")),
        "revision_windows": revision_coverage,
        "rolling_actuals": D(q["rolling_history_coverage"]),
    }
    history = min(history_parts.values())
    multiplier = p("confidence_sample_floor") + (1 - p("confidence_sample_floor")) * history
    composite = evidence * quality * multiplier
    return {
        "evidence_confidence": evidence,
        "data_quality_confidence": quality,
        "history_sufficiency": history,
        "composite_confidence": composite,
        "probability_confidence": quality * multiplier,
        "raw_candidate": candidate,
        "confidence_components": {
            "evidence": parts,
            "history": history_parts,
            "history_multiplier": multiplier,
            "observation_completeness": D(q["observation_completeness"]),
            "active_penalty_fraction": penalty,
            "active_penalty_count": len(q["active_penalties"]),
            "historical_error_magnitude_diagnostic": pack["features"]["forecast_error_history"],
            "interval_width_diagnostic": pack["features"]["forecast_interval_width"],
            "forecast_sample_count": samples,
        },
    }


def classify_corrected(pack, history, policy=POLICY):
    return classify(pack, history, policy, confidence_model=confidence_components)


CONTRACT_FIELDS = (
    "policy_version",
    "as_of",
    "confirmed_regime",
    "candidate_regime",
    "probabilities",
    "transition_status",
    "cycle_score",
    "evidence_confidence",
    "data_quality_confidence",
    "history_sufficiency",
    "composite_confidence",
    "candidate_probability",
    "probability_gap_to_second_candidate",
    "reason_codes",
    "candidate_streak",
    "confidence_components",
)


def output_contract(state, forecast_run_id):
    if (
        not isinstance(forecast_run_id, int)
        or isinstance(forecast_run_id, bool)
        or forecast_run_id <= 0
    ):
        raise ValueError("A valid forecast identity is required")
    missing = set(CONTRACT_FIELDS) - set(state)
    if missing:
        raise ValueError(
            "Incomplete regime envelope; confirmed-only consumption is forbidden: "
            + ", ".join(sorted(missing))
        )
    if (
        set(state["probabilities"]) != set(REGIMES)
        or sum(D(v) for v in state["probabilities"].values()) != 1
    ):
        raise ValueError("Full normalized five-regime probability vector required")
    if state["confirmed_regime"] not in REGIMES or state["candidate_regime"] not in REGIMES:
        raise ValueError("Only the five economic regimes are valid")
    if any(not 0 <= D(v) <= 1 for v in state["probabilities"].values()):
        raise ValueError("Invalid probability component")
    for key in (
        "evidence_confidence",
        "data_quality_confidence",
        "history_sufficiency",
        "composite_confidence",
        "candidate_probability",
        "probability_gap_to_second_candidate",
    ):
        if not 0 <= D(state[key]) <= 1:
            raise ValueError("Invalid confidence component: " + key)
    candidate_probability = D(state["probabilities"][state["candidate_regime"]])
    gap = candidate_probability - max(
        D(v) for k, v in state["probabilities"].items() if k != state["candidate_regime"]
    )
    if (
        D(state["candidate_probability"]) != candidate_probability
        or D(state["probability_gap_to_second_candidate"]) != gap
    ):
        raise ValueError("Candidate evidence does not match the probability vector")
    if state["transition_status"] not in (
        "STABLE",
        "PENDING_CONFIRMATION",
        "LOW_CONFIDENCE",
        "STRONG_OVERRIDE_PENDING_GUARD",
    ):
        raise ValueError("Invalid transition status")
    return canonical(
        {
            "contract_version": "RegimeOutputV1.1",
            "forecast_run_id": forecast_run_id,
            "quarter": state["quarter"],
            "scores": state["scores"],
            **{k: state[k] for k in CONTRACT_FIELDS},
            "blocked_regime": state.get("blocked_regime"),
            "structural_eligible": state["structural_eligible"],
            "stress_streak": state["stress_streak"],
        }
    )


def snapshot_contract(row):
    if row.policy_version != POLICY["version"] or not row.metadata_json:
        raise ValueError(
            "Legacy snapshots require explicit legacy handling; no silent confidence upgrade"
        )
    state = row.metadata_json["state"]
    for key in ("confirmed_regime", "candidate_regime", "transition_status"):
        if getattr(row, key) != state[key]:
            raise ValueError("Mixed or inconsistent snapshot envelope")
    for key in (
        "evidence_confidence",
        "data_quality_confidence",
        "history_sufficiency",
        "composite_confidence",
        "candidate_probability",
        "probability_gap_to_second_candidate",
    ):
        if getattr(row, key) != D(state[key]):
            raise ValueError("Mixed snapshot confidence components")
    result = output_contract(state, row.forecast_run_id)
    result["snapshot_id"] = row.id
    result["quality_lineage"] = row.metadata_json["inputs"]["quality_lineage"]
    return result
