"""
StockOS Signal Fusion Engine.
Synthesizes 4 core fundamental research pillars into auditable portfolio allocation signals:
1. Valuation Bridge (Dual-track Quant Baseline & AI-informed expectations gap)
2. Macro / Industry Regime (Confirmed regime, transition state, regime confidence)
3. Quantitative Forecast Revision (Direction, magnitude, and momentum of management guidance)
4. Tail-Risk Governance (Advisory challenge haircuts and downside penalties)
"""

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Any

from valuation_engine.db.store import digest
from valuation_engine.regime.confidence import POLICY as CORRECTED_POLICY
from valuation_engine.regime.confidence import output_contract
from valuation_engine.regime.policy import LAYERS
from valuation_engine.regime.service import payload
from valuation_engine.research.numbers import D, canonical
from valuation_engine.time import aware
from valuation_engine.valuation.bridge import ValuationBridgeResult


def validate_formal_regime(envelope: dict[str, Any]) -> dict[str, Any]:
    """Validate the atomic corrected envelope and preserve all its source diagnostics."""
    try:
        if (
            envelope["contract_version"] != "RegimeOutputV1.1"
            or envelope["policy_version"] != CORRECTED_POLICY["version"]
            or envelope["assumption_hash"] != digest(payload(CORRECTED_POLICY))
        ):
            raise ValueError("Expected the current corrected RegimeOutputV1.1 policy")
        output_contract(envelope, envelope["forecast_run_id"])
        for key in ("snapshot_id", "company_id", "input_snapshot_id"):
            if type(envelope[key]) is not int or envelope[key] <= 0:
                raise ValueError("Invalid formal Regime identity: " + key)
        as_of = aware(datetime.fromisoformat(envelope["as_of"]))
        checkpoint = aware(datetime.fromisoformat(envelope["checkpoint_timestamp"]))
        if as_of > checkpoint:
            raise ValueError("Regime information cutoff is after its checkpoint")
        for key in ("candidate_streak", "stress_streak"):
            if type(envelope[key]) is not int or envelope[key] < 0:
                raise ValueError("Invalid transition counter: " + key)
        if type(envelope["structural_eligible"]) is not bool or envelope["blocked_regime"] not in (
            None,
            "Structural Deterioration",
        ):
            raise ValueError("Invalid structural guard metadata")
        if not isinstance(envelope["reason_codes"], list) or not all(
            isinstance(code, str) for code in envelope["reason_codes"]
        ):
            raise ValueError("Invalid Regime reason codes")
        components = envelope["confidence_components"]
        required_components = {
            "evidence",
            "history",
            "history_multiplier",
            "observation_completeness",
            "active_penalty_fraction",
            "active_penalty_count",
            "historical_error_magnitude_diagnostic",
            "interval_width_diagnostic",
            "forecast_sample_count",
        }
        if not isinstance(components, dict) or not required_components <= components.keys():
            raise ValueError("Missing Regime confidence diagnostics")
        for key, fields in (
            (
                "evidence",
                {
                    "candidate_probability",
                    "separation",
                    "support_breadth",
                    "score_consistency",
                    "evidence_strength",
                },
            ),
            ("history", {"forecast_error_samples", "revision_windows", "rolling_actuals"}),
        ):
            if not isinstance(components[key], dict) or not fields <= components[key].keys():
                raise ValueError("Missing Regime confidence diagnostics: " + key)
            if any(not 0 <= D(components[key][field]) <= 1 for field in fields):
                raise ValueError("Invalid Regime confidence diagnostics: " + key)
        for key in ("history_multiplier", "observation_completeness", "active_penalty_fraction"):
            if not 0 <= D(components[key]) <= 1:
                raise ValueError("Invalid Regime confidence diagnostic: " + key)
        samples = D(components["forecast_sample_count"])
        if not samples.is_finite() or samples < 0 or samples != samples.to_integral_value():
            raise ValueError("Invalid Regime forecast sample count")
        if (
            type(components["active_penalty_count"]) is not int
            or components["active_penalty_count"] < 0
        ):
            raise ValueError("Invalid Regime active penalty count")
        if envelope["transition_status"] == "STRONG_OVERRIDE_PENDING_GUARD" and (
            envelope["blocked_regime"] != "Structural Deterioration"
            or envelope["structural_eligible"]
        ):
            raise ValueError("Inconsistent pending structural guard")
        if set(envelope["scores"]) != set(LAYERS) or any(
            value is not None and not -1 <= D(value) <= 1 for value in envelope["scores"].values()
        ):
            raise ValueError("Invalid Regime scores")
        if envelope["cycle_score"] is not None and not -100 <= D(envelope["cycle_score"]) <= 100:
            raise ValueError("Invalid Regime cycle score")
        stress = envelope["stress_dimensions"]
        if set(stress) != {"growth", "revision", "margin", "cash"} or any(
            type(value) is not bool for value in stress.values()
        ):
            raise ValueError("Invalid Regime stress dimensions")
        inputs = envelope["input_lineage"]
        if any(
            inputs[key] != envelope[key]
            for key in ("forecast_run_id", "input_snapshot_id", "quarter")
        ) or (
            aware(datetime.fromisoformat(inputs["as_of"])) != as_of
            or inputs["quality_lineage"] != envelope["quality_lineage"]
        ):
            raise ValueError("Mixed Regime input lineage")
        for key in ("feature_lineage", "input_observations", "quality_lineage"):
            if not isinstance(inputs[key], dict):
                raise ValueError("Missing Regime input lineage: " + key)
        quality = inputs["quality_lineage"]
        if (
            not {
                "active_observation_ids",
                "active_penalties",
                "excluded_warnings",
                "observation_completeness",
                "rolling_history_coverage",
                "required_observations",
                "present_observations",
                "quality_ledger_preserved",
            }
            <= quality.keys()
            or not inputs["feature_lineage"]
            or not inputs["input_observations"]
        ):
            raise ValueError("Incomplete Regime quality/input lineage")
        for key in ("active_observation_ids", "active_penalties", "excluded_warnings"):
            if not isinstance(quality[key], list):
                raise ValueError("Invalid Regime quality lineage: " + key)
        for key in ("observation_completeness", "rolling_history_coverage"):
            if not 0 <= D(quality[key]) <= 1:
                raise ValueError("Invalid Regime quality fraction: " + key)
        for key in ("required_observations", "present_observations"):
            if type(quality[key]) is not int or quality[key] < 0:
                raise ValueError("Invalid Regime observation count")
        if (
            quality["present_observations"] > quality["required_observations"]
            or quality["quality_ledger_preserved"] is not True
        ):
            raise ValueError("Invalid Regime quality ledger")
        if any(
            node not in inputs["input_observations"] for node in quality["active_observation_ids"]
        ):
            raise ValueError("Dangling Regime active observation")
        if any(
            not isinstance(edges, list)
            or any(node not in inputs["input_observations"] for node in edges)
            for edges in inputs["feature_lineage"].values()
        ):
            raise ValueError("Dangling Regime input lineage")
    except (KeyError, TypeError, ArithmeticError, AttributeError) as exc:
        raise ValueError("Invalid or incomplete formal Regime envelope") from exc
    return canonical(deepcopy(envelope))


@dataclass(frozen=True)
class RegimeInput:
    confirmed_regime: str  # e.g., "Hypergrowth", "Growth", "Mature Growth", "Cyclical Downturn", "Structural Deterioration"
    candidate_regime: str
    transition_status: str  # "STABLE", "TRANSITION", "VOLATILE"
    confidence: float  # [0.0, 1.0]
    stress_dimensions: dict[str, bool] = field(
        default_factory=dict
    )  # {"growth": False, "margin": False, "cash": True}


@dataclass(frozen=True)
class ForecastRevisionInput:
    revenue_revision_pct: float  # e.g., +0.104 (+10.4%)
    eps_revision_pct: float
    fcf_revision_pct: float
    revision_direction: str  # "UPWARD", "NEUTRAL", "DOWNWARD"


@dataclass(frozen=True)
class FusedDecisionResult:
    quarter: str
    as_of_date: str
    equity_weight: float
    cash_weight: float
    action: str  # "STRONG_ACCUMULATE", "OVERWEIGHT", "NEUTRAL_TILT", "CORE_ONLY", "CAPITAL_PRESERVATION"
    primary_rationale: str

    # Nominal pillar adjustments; the final regime-cap correction is in audit_trail.
    base_valuation_weight: float
    regime_adjustment: float
    revision_adjustment: float
    tail_risk_adjustment: float

    # Pillar Snapshots
    valuation_summary: dict[str, Any]
    regime_summary: dict[str, Any]
    revision_summary: dict[str, Any]
    audit_trail: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SignalFusionEngine:
    """
    Fuses quantitative valuation, regime dynamics, forecast revisions, and AI tail risk
    into a deterministic, constrained allocation decision.
    """

    REGIME_WEIGHT_CAPS = {
        "Hypergrowth": 1.00,
        "Growth": 1.00,
        "Mature Growth": 0.85,
        "Cyclical Downturn": 0.40,
        "Structural Deterioration": 0.00,
    }

    def fuse_formal(
        self,
        valuation: ValuationBridgeResult,
        regime: dict[str, Any],
        forecast_revision: ForecastRevisionInput | None = None,
    ) -> FusedDecisionResult:
        """Consume the full formal contract; project only for unchanged legacy arithmetic."""
        envelope = validate_formal_regime(regime)
        if envelope["quarter"] != valuation.quarter or (
            aware(datetime.fromisoformat(envelope["checkpoint_timestamp"])).date().isoformat()
            != valuation.as_of_date
        ):
            raise ValueError("Formal Regime and valuation checkpoint do not match")
        scalar = RegimeInput(
            confirmed_regime=envelope["confirmed_regime"],
            candidate_regime=envelope["candidate_regime"],
            transition_status=envelope["transition_status"],
            confidence=float(envelope["composite_confidence"]),
            stress_dimensions=envelope["stress_dimensions"],
        )
        return replace(self.fuse(valuation, scalar, forecast_revision), regime_summary=envelope)

    def fuse(
        self,
        valuation: ValuationBridgeResult,
        regime: RegimeInput | None = None,
        forecast_revision: ForecastRevisionInput | None = None,
    ) -> FusedDecisionResult:
        """Explicit legacy/scalar entry point; formal cadence must use fuse_formal."""
        audit_trail: list[str] = []

        # 1. Base Valuation Allocation (from Valuation Bridge Expectations Gap)
        ai_gap = valuation.ai_expectations_gap
        if ai_gap >= 0.05 or valuation.valuation_stance == "UNDERVALUED":
            base_weight = 1.00
            audit_trail.append(
                f"Valuation Pillar: Positive expectations gap (+{ai_gap * 100:.1f}%) supports 100% equity."
            )
        elif ai_gap >= -0.15:
            base_weight = 0.85
            audit_trail.append(
                f"Valuation Pillar: Fair value channel ({ai_gap * 100:.1f}%) establishes 85% core equity."
            )
        elif ai_gap >= -0.30:
            base_weight = 0.60
            audit_trail.append(
                f"Valuation Pillar: Moderate multiple premium ({ai_gap * 100:.1f}%) establishes 60% tilted equity."
            )
        else:
            base_weight = 0.40
            audit_trail.append(
                f"Valuation Pillar: High expectations hurdle ({ai_gap * 100:.1f}%) establishes 40% defensive baseline."
            )

        effective_weight = base_weight

        # 2. Regime Modulation
        regime_adj = 0.0
        regime_summary = {}
        cap = self.REGIME_WEIGHT_CAPS.get(regime.confirmed_regime, 1.00) if regime else 1.00
        if regime:
            regime_summary = asdict(regime)
            # Check regime cap
            if effective_weight > cap:
                regime_adj = cap - effective_weight
                effective_weight = cap
                audit_trail.append(
                    f"Regime Pillar: Confirmed regime '{regime.confirmed_regime}' limits maximum equity weight to {cap * 100:.0f}%."
                )

            # Check transition instability or low confidence
            if regime.transition_status != "STABLE" or regime.confidence < 0.40:
                instability_cut = -0.10
                regime_adj += instability_cut
                effective_weight = max(0.20, effective_weight + instability_cut)
                audit_trail.append(
                    f"Regime Pillar: Regime status '{regime.transition_status}' with low confidence ({regime.confidence:.2f}) applies a 10% caution buffer."
                )
        else:
            audit_trail.append("Regime Pillar: Default neutral regime assumed.")

        # 3. Forecast Revision Modulation
        revision_adj = 0.0
        revision_summary = {}
        if forecast_revision:
            revision_summary = asdict(forecast_revision)
            # Downward revisions require conservative adjustments
            if (
                forecast_revision.revision_direction == "DOWNWARD"
                or forecast_revision.revenue_revision_pct < -0.03
            ):
                downward_cut = -0.15
                revision_adj = downward_cut
                effective_weight = max(0.20, effective_weight + downward_cut)
                audit_trail.append(
                    f"Forecast Revision Pillar: Management downward revision ({forecast_revision.revenue_revision_pct * 100:.1f}%) trims equity by 15%."
                )
            elif forecast_revision.revenue_revision_pct >= 0.08:
                # Strong upward revision reinforces momentum if space permits
                if effective_weight < 1.0 and ai_gap >= -0.20:
                    upward_bonus = +0.10
                    revision_adj = upward_bonus
                    effective_weight = min(1.0, effective_weight + upward_bonus)
                    audit_trail.append(
                        f"Forecast Revision Pillar: Strong upward revision (+{forecast_revision.revenue_revision_pct * 100:.1f}%) adds 10% allocation bonus."
                    )
        else:
            audit_trail.append("Forecast Revision Pillar: Default carry-forward assumed.")

        # 4. Tail Risk Governance Check
        tail_adj = 0.0
        if valuation.tail_risk_haircut < 0.90:
            tail_cut = -0.10
            tail_adj = tail_cut
            effective_weight = max(0.20, effective_weight + tail_cut)
            audit_trail.append(
                f"Tail Risk Pillar: Heavy downside challenge haircut ({valuation.tail_risk_haircut:.2f}) applies 10% risk haircut."
            )

        # Reapply the hard regime cap after bonuses and adjustment floors.
        if regime and effective_weight > cap:
            audit_trail.append(
                f"Final Regime Guard: Confirmed regime '{regime.confirmed_regime}' caps post-adjustment equity "
                f"from {effective_weight * 100:.0f}% to {cap * 100:.0f}% "
                f"(reduction of {(effective_weight - cap) * 100:.0f} percentage points)."
            )

        # Final clamping and action labeling
        final_equity_w = round(max(0.0, min(1.0, cap, effective_weight)), 2)
        final_cash_w = round(1.0 - final_equity_w, 2)

        if final_equity_w >= 0.95:
            action = "STRONG_ACCUMULATE"
        elif final_equity_w >= 0.75:
            action = "OVERWEIGHT"
        elif final_equity_w >= 0.50:
            action = "NEUTRAL_TILT"
        elif final_equity_w >= 0.30:
            action = "CORE_ONLY"
        else:
            action = "CAPITAL_PRESERVATION"

        primary_rationale = (
            f"決策融合：以估值預期差 ({ai_gap * 100:+.1f}%) 為核心，"
            f"經 Regime ('{regime.confirmed_regime if regime else 'Neutral'}') 與財測修正調整後，"
            f"配置 {final_equity_w * 100:.0f}% 股票，{final_cash_w * 100:.0f}% 現金。"
        )

        return FusedDecisionResult(
            quarter=valuation.quarter,
            as_of_date=valuation.as_of_date,
            equity_weight=final_equity_w,
            cash_weight=final_cash_w,
            action=action,
            primary_rationale=primary_rationale,
            base_valuation_weight=round(base_weight, 2),
            regime_adjustment=round(regime_adj, 2),
            revision_adjustment=round(revision_adj, 2),
            tail_risk_adjustment=round(tail_adj, 2),
            valuation_summary=valuation.to_dict(),
            regime_summary=regime_summary,
            revision_summary=revision_summary,
            audit_trail=audit_trail,
        )
