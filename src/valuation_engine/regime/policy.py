"""Pure deterministic scores, confidence normalization and state transitions."""

import json
from copy import deepcopy
from decimal import ROUND_FLOOR
from pathlib import Path

from valuation_engine.research.numbers import D, canonical, mean

POLICY = json.loads(Path(__file__).with_name("policy_v1.json").read_text())
LAYERS = ("growth", "revision", "profitability", "cash_quality", "deterioration")
REGIMES = tuple(POLICY["prototypes"])


def clip(x, low=-1, high=1):
    return max(low, min(high, x)) if x is not None else None


def numeric(features):
    return {k: D(str(v)) if v is not None else None for k, v in features.items()}


def weighted(values, weights):
    usable = [(values[k], D(str(w))) for k, w in weights.items() if values.get(k) is not None]
    return sum(v * w for v, w in usable) / sum(w for _, w in usable) if usable else None


def classify(pack, history, policy=POLICY, confidence_model=None):
    f = numeric(pack["features"])

    def p(k):
        return D(str(policy[k]))

    def scale(key, center, size):
        x = f.get(key)
        return clip((x - center) / size) if x is not None else None

    def avg(values):
        return mean([x for x in values if x is not None])

    def delta(a, b):
        return f[a] - f[b] if f.get(a) is not None and f.get(b) is not None else None

    growth = []
    for name in (
        "revenue_yoy",
        "eps_yoy",
        "fcf_yoy",
        "ntm_revenue_growth",
        "fy1_revenue_growth",
        "fy2_revenue_growth",
        "ntm_eps_growth",
        "fy1_eps_growth",
        "fy2_eps_growth",
    ):
        size = (
            p("eps_growth_scale")
            if "eps" in name
            else p("fcf_growth_scale")
            if "fcf" in name
            else p("revenue_growth_scale")
        )
        growth.append(scale(name, p("growth_center"), size))
    revision = []
    for prefix in ("", "trailing_2q_", "trailing_4q_"):
        for metric in ("revenue", "eps", "fcf", "gross_margin", "operating_margin"):
            revision.append(
                scale(
                    prefix + metric + "_revision",
                    D(0),
                    p("margin_revision_scale") if "margin" in metric else p("revision_scale"),
                )
            )
        breadth = f.get(prefix + "revision_breadth")
        revision.append(2 * breadth - 1 if breadth is not None else None)
    margin_changes = [
        scale(k + "_change", D(0), p("margin_change_scale"))
        for k in ("gross_margin", "operating_margin", "fcf_margin")
    ]
    margin_direction = avg(margin_changes)
    levels = [
        scale(k, p(k + "_center"), p(k + "_scale"))
        for k in ("gross_margin", "operating_margin", "fcf_margin")
    ]
    working = avg(
        [
            clip(-delta(k, "revenue_yoy") / p("working_capital_excess_scale"))
            if delta(k, "revenue_yoy") is not None
            else None
            for k in ("ar_growth", "inventory_growth")
        ]
    )
    cash_divergence = (
        clip(delta("fcf_yoy", "revenue_yoy") / p("fcf_growth_scale"))
        if delta("fcf_yoy", "revenue_yoy") is not None
        else None
    )
    sbc = scale("sbc_to_revenue", p("sbc_center"), p("sbc_scale"))
    scores = {
        "growth": avg(growth),
        "revision": avg(revision),
        "profitability": avg(levels + margin_changes),
        "cash_quality": avg(
            [levels[2], cash_divergence, working, -sbc if sbc is not None else None]
        ),
    }
    scores["deterioration"] = avg(
        [
            -x if x is not None else None
            for x in (
                scores["growth"],
                scores["revision"],
                margin_direction,
                scores["cash_quality"],
            )
        ]
    )
    coverage_keys = [
        k
        for k in f
        if k
        not in (
            "fcf_growth",
            "forecast_sample_count",
            "forecast_interval_width",
            "forecast_error_history",
        )
    ]
    coverage = (
        D(sum(f[k] is not None for k in coverage_keys)) / len(coverage_keys)
        if coverage_keys
        else D(0)
    )
    anomaly_count = sum(w["reason"] == "margin_anomaly" for w in pack["warnings"])
    share_warning = any("basis" in w["reason"] for w in pack["warnings"])
    penalty = min(
        p("maximum_anomaly_quality_penalty"),
        anomaly_count * p("margin_anomaly_quality_penalty")
        + int(share_warning) * p("share_warning_quality_penalty"),
    )
    quality = coverage * (1 - penalty)
    sample = min(D(1), (f.get("forecast_sample_count") or D(0)) / p("confidence_full_samples"))
    sample_factor = p("confidence_sample_floor") + (1 - p("confidence_sample_floor")) * sample
    error = f.get("forecast_error_history")
    width = f.get("forecast_interval_width")
    error_factor = (
        max(p("confidence_min_error_factor"), 1 / (1 + error / p("confidence_error_scale")))
        if error is not None
        else p("confidence_min_error_factor")
    )
    width_factor = (
        1 / (1 + width / p("interval_width_scale"))
        if width is not None
        else p("confidence_sample_floor")
    )
    confidence = quality * sample_factor * avg([error_factor, width_factor])
    stress = {
        "growth": f.get("revenue_yoy") is not None and f["revenue_yoy"] < 0,
        "revision": all(
            f.get(k) is not None and f[k] < p("structural_revision_threshold")
            for k in ("revenue_revision", "eps_revision")
        ),
        "margin": f.get("operating_margin_change") is not None
        and f["operating_margin_change"] < p("structural_margin_threshold"),
        "cash": f.get("fcf_margin_change") is not None
        and f["fcf_margin_change"] < p("structural_margin_threshold"),
    }
    stressed = (
        stress["growth"]
        and stress["revision"]
        and sum(stress.values()) >= policy["structural_min_independent_dimensions"]
    )
    consecutive = bool(history) and history[-1]["quarter_index"] == pack["quarter_index"] - 1
    streak = (history[-1]["stress_streak"] if consecutive else 0) + 1 if stressed else 0
    structural = streak >= policy["structural_consecutive_quarters"]
    strengths = {}
    for regime, prototype in policy["prototypes"].items():
        distance = weighted(
            {
                key: (scores[key] - D(target)) ** 2 if scores[key] is not None else None
                for key, target in zip(LAYERS, prototype, strict=True)
            },
            policy["layer_weights"],
        )
        strengths[regime] = (
            (-distance / p("prototype_temperature")).exp() if distance is not None else D(1)
        )
        if regime == "Structural Deterioration" and not structural:
            strengths[regime] = D(0)
    components = confidence_model(pack, scores, strengths, policy) if confidence_model else None
    if components is not None:
        confidence = components["composite_confidence"]
        quality = components["data_quality_confidence"]
    probability_confidence = components["probability_confidence"] if components else confidence
    total = sum(strengths.values())
    eligible = [r for r in REGIMES if r != "Structural Deterioration" or structural]
    probs = {
        r: probability_confidence * strengths[r] / total
        + (1 - probability_confidence) / len(eligible)
        if r in eligible
        else D(0)
        for r in REGIMES
    }
    order = policy["tie_order"]
    candidate = components["raw_candidate"] if components else max(order, key=lambda r: probs[r])
    quantum = D(1).scaleb(-policy["probability_decimal_places"])
    if components is None:
        probs = {r: x.quantize(quantum) for r, x in probs.items()}
        probs[candidate] += 1 - sum(probs.values())
    else:
        exact = dict(probs)
        probs = {
            r: (x / quantum).to_integral_value(rounding=ROUND_FLOOR) * quantum
            for r, x in exact.items()
        }
        remaining = int((1 - sum(probs.values())) / quantum)
        ranked = sorted(order, key=lambda r: exact[r] - probs[r], reverse=True)
        for r in ranked[:remaining]:
            probs[r] += quantum
    previous = history[-1] if consecutive else None
    prior_regime = previous["primary_regime"] if previous else None
    confirmation = (
        previous["candidate_streak"] + 1
        if previous and previous["candidate_regime"] == candidate
        else 1
    )
    if confidence < p("transition_min_confidence"):
        confirmation = 0
    primary, decision = (
        prior_regime or candidate,
        "INITIAL_STATE" if previous is None else "STATE_RETAINED",
    )
    negative = all(
        scores[k] is not None and scores[k] <= p("strong_negative_score")
        for k in ("growth", "revision", "profitability")
    ) and quality >= p("strong_negative_quality")
    gap = probs[candidate] - probs.get(prior_regime, D(0))
    support = sum(
        scores[k] is not None
        and (
            scores[k] >= p("strong_independent_score")
            if candidate in ("Hypergrowth", "Growth")
            else scores[k] <= -p("strong_independent_score")
        )
        for k in ("growth", "revision", "profitability", "cash_quality")
    )
    if prior_regime and negative:
        primary = "Structural Deterioration" if structural else "Cyclical Downturn"
        decision = "STRONG_NEGATIVE_OVERRIDE"
    elif prior_regime and candidate != prior_regime:
        if (
            gap >= p("strong_transition_gap")
            and confidence >= p("strong_transition_confidence")
            and support >= 2
        ):
            primary, decision = candidate, "STRONG_EVIDENCE_TRANSITION"
        elif confirmation >= policy["transition_confirmations"] and confidence >= p(
            "transition_min_confidence"
        ):
            primary, decision = candidate, "PERSISTENCE_CONFIRMED"
        else:
            decision = "PERSISTENCE_PENDING"
    # No persisted structural state is allowed once the required window ceases to hold.
    if primary == "Structural Deterioration" and not structural:
        primary, decision = candidate, "STRUCTURAL_GUARD_RELEASED"
    cycle_components = {
        "acceleration": scale("growth_acceleration", D(0), p("revenue_growth_scale")),
        "revision": scores["revision"],
        "margin": margin_direction,
        "working_capital": working,
        "cash": cash_divergence,
    }
    cycle = weighted(cycle_components, policy["cycle_weights"])
    reasons = [decision]
    for key, code, sign in (
        ("growth_acceleration", "GROWTH_ACCELERATION", 1),
        ("growth_acceleration", "GROWTH_DECELERATION", -1),
        ("eps_revision", "REVISION_ACCELERATION", 1),
        ("operating_margin_change", "MARGIN_COMPRESSION", -1),
    ):
        if f.get(key) is not None and f[key] * sign > 0:
            reasons.append(code)
    if working is not None and working < 0:
        reasons.append("CYCLICAL_PRESSURE")
    if cash_divergence is not None and cash_divergence < 0:
        reasons.append("CASH_FLOW_DIVERGENCE")
    if stressed:
        reasons.append("PERSISTENT_NEGATIVE_REVISIONS" if streak > 1 else "NEGATIVE_REVISION_SHOCK")
    if prior_regime in ("Cyclical Downturn", "Structural Deterioration") and primary in (
        "Growth",
        "Hypergrowth",
        "Mature Growth",
    ):
        reasons.append("RECOVERY")
    if not structural:
        reasons.append("STRUCTURAL_EVIDENCE_INSUFFICIENT")
    if quality < 1:
        reasons.append("INCOMPLETE_OR_ANOMALOUS_INPUTS")
    result = {
        "quarter": pack["quarter"],
        "quarter_index": pack["quarter_index"],
        "as_of": pack["as_of"],
        "primary_regime": primary,
        "candidate_regime": candidate,
        "candidate_streak": confirmation,
        "probabilities": probs,
        "scores": scores,
        "cycle_score": cycle * 100 if cycle is not None else None,
        "cycle_components": cycle_components,
        "confidence": confidence,
        "data_quality_score": quality,
        "quality_components": {
            "coverage": coverage,
            "anomaly_penalty": penalty,
            "sample_factor": sample_factor,
            "error_factor": error_factor,
            "width_factor": width_factor,
        },
        "stress_dimensions": stress,
        "stress_streak": streak,
        "structural_eligible": structural,
        "reason_codes": reasons,
        "transition_strength": max(D(0), gap),
        "previous_regime": prior_regime,
        "policy_version": policy["version"],
    }
    if components is not None:
        structural_distance = weighted(
            {
                k: (scores[k] - D(target)) ** 2 if scores[k] is not None else None
                for k, target in zip(
                    LAYERS, policy["prototypes"]["Structural Deterioration"], strict=True
                )
            },
            policy["layer_weights"],
        )
        structural_strength = (
            (-structural_distance / p("prototype_temperature")).exp()
            if structural_distance is not None
            else D(0)
        )
        blocked = negative and not structural and structural_strength > max(strengths.values())
        status = (
            "LOW_CONFIDENCE"
            if confidence < p("transition_min_confidence")
            else "STRONG_OVERRIDE_PENDING_GUARD"
            if blocked
            else "PENDING_CONFIRMATION"
            if primary != candidate
            else "STABLE"
        )
        result.update(
            {
                k: v
                for k, v in components.items()
                if k not in ("probability_confidence", "raw_candidate")
            }
        )
        result.update(
            confirmed_regime=primary,
            transition_status=status,
            candidate_probability=probs[candidate],
            probability_gap_to_second_candidate=probs[candidate]
            - max(v for k, v in probs.items() if k != candidate),
            blocked_regime="Structural Deterioration" if blocked else None,
        )
        result["quality_components"] = components["confidence_components"]
    return canonical(result)


def sensitivity_policies(policy=POLICY):
    fraction = D(policy["sensitivity_fraction"])
    for direction in (-1, 1):
        factor = 1 + direction * fraction
        variant = deepcopy(policy)
        for key in policy:
            if key.endswith("_scale") or key in (
                "growth_center",
                "gross_margin_center",
                "operating_margin_center",
                "fcf_margin_center",
                "sbc_center",
            ):
                variant[key] = str(D(policy[key]) * factor)
        yield f"score_scales_centers_{direction:+d}", variant
        for key in LAYERS:
            variant = deepcopy(policy)
            variant["layer_weights"][key] = str(D(policy["layer_weights"][key]) * factor)
            yield f"{key}_weight_{direction:+d}", variant
        variant = deepcopy(policy)
        variant["strong_transition_gap"] = str(D(policy["strong_transition_gap"]) * factor)
        yield f"transition_gap_{direction:+d}", variant
