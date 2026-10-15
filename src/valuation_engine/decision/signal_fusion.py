"""
StockOS Signal Fusion Engine.
Synthesizes 4 core fundamental research pillars into auditable portfolio allocation signals:
1. Valuation Bridge (Dual-track Quant Baseline & AI-informed expectations gap)
2. Macro / Industry Regime (Confirmed regime, transition state, regime confidence)
3. Quantitative Forecast Revision (Direction, magnitude, and momentum of management guidance)
4. Tail-Risk Governance (Advisory challenge haircuts and downside penalties)
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from valuation_engine.valuation.bridge import ValuationBridgeResult


@dataclass(frozen=True)
class RegimeInput:
    confirmed_regime: str  # e.g., "Hypergrowth", "Growth", "Mature Growth", "Cyclical Downturn", "Structural Deterioration"
    candidate_regime: str
    transition_status: str  # "STABLE", "TRANSITION", "VOLATILE"
    confidence: float  # [0.0, 1.0]
    stress_dimensions: Dict[str, bool] = field(default_factory=dict)  # {"growth": False, "margin": False, "cash": True}


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
    valuation_summary: Dict[str, Any]
    regime_summary: Dict[str, Any]
    revision_summary: Dict[str, Any]
    audit_trail: List[str]

    def to_dict(self) -> Dict[str, Any]:
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

    def fuse(
        self,
        valuation: ValuationBridgeResult,
        regime: Optional[RegimeInput] = None,
        forecast_revision: Optional[ForecastRevisionInput] = None,
    ) -> FusedDecisionResult:
        audit_trail: List[str] = []

        # 1. Base Valuation Allocation (from Valuation Bridge Expectations Gap)
        ai_gap = valuation.ai_expectations_gap
        if ai_gap >= 0.05 or valuation.valuation_stance == "UNDERVALUED":
            base_weight = 1.00
            audit_trail.append(f"Valuation Pillar: Positive expectations gap (+{ai_gap*100:.1f}%) supports 100% equity.")
        elif ai_gap >= -0.15:
            base_weight = 0.85
            audit_trail.append(f"Valuation Pillar: Fair value channel ({ai_gap*100:.1f}%) establishes 85% core equity.")
        elif ai_gap >= -0.30:
            base_weight = 0.60
            audit_trail.append(f"Valuation Pillar: Moderate multiple premium ({ai_gap*100:.1f}%) establishes 60% tilted equity.")
        else:
            base_weight = 0.40
            audit_trail.append(f"Valuation Pillar: High expectations hurdle ({ai_gap*100:.1f}%) establishes 40% defensive baseline.")

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
                    f"Regime Pillar: Confirmed regime '{regime.confirmed_regime}' limits maximum equity weight to {cap*100:.0f}%."
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
            if forecast_revision.revision_direction == "DOWNWARD" or forecast_revision.revenue_revision_pct < -0.03:
                downward_cut = -0.15
                revision_adj = downward_cut
                effective_weight = max(0.20, effective_weight + downward_cut)
                audit_trail.append(
                    f"Forecast Revision Pillar: Management downward revision ({forecast_revision.revenue_revision_pct*100:.1f}%) trims equity by 15%."
                )
            elif forecast_revision.revenue_revision_pct >= 0.08:
                # Strong upward revision reinforces momentum if space permits
                if effective_weight < 1.0 and ai_gap >= -0.20:
                    upward_bonus = +0.10
                    revision_adj = upward_bonus
                    effective_weight = min(1.0, effective_weight + upward_bonus)
                    audit_trail.append(
                        f"Forecast Revision Pillar: Strong upward revision (+{forecast_revision.revenue_revision_pct*100:.1f}%) adds 10% allocation bonus."
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
                f"from {effective_weight*100:.0f}% to {cap*100:.0f}% "
                f"(reduction of {(effective_weight-cap)*100:.0f} percentage points)."
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
            f"決策融合：以估值預期差 ({ai_gap*100:+.1f}%) 為核心，"
            f"經 Regime ('{regime.confirmed_regime if regime else 'Neutral'}') 與財測修正調整後，"
            f"配置 {final_equity_w*100:.0f}% 股票，{final_cash_w*100:.0f}% 現金。"
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
