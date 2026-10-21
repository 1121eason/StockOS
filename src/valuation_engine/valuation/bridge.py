"""Valuation Bridge V2 — Fuses FSI Qualitative Intelligence with DCF Quant Valuation.

Architectural contract:
1. Quant Baseline Purity: Preserves quant DCF, Reverse DCF market-implied growth, and quant expectations gap.
2. Double-Counting Guard: Dampens positive AI qualitative features if quantitative guidance revision already captured upside.
3. Structural Risk & Growth Channels: Explains fair value adjustments via explicit parameter sensitivities.
"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ValuationBridgeResult:
    quarter: str
    as_of_date: str
    market_price: float

    # 1. Quant Baseline (Zero AI intervention)
    quant_dcf_base: float
    quant_expectations_gap: float
    market_implied_growth_rate: float | None
    quant_forecast_growth_rate: float | None

    # 2. AI Qualitative Intelligence & Tail Haircuts
    ai_composite_score: float
    tail_risk_haircut: float

    # 3. Scenario Valuation Channels
    ai_fair_value_base: float
    ai_fair_value_bull: float
    ai_fair_value_bear: float
    ai_fair_value_stress: float

    # 4. Expectations Gaps & Stance
    expectations_gap: float  # AI gap (retained for backward compatibility)
    ai_expectations_gap: float
    valuation_stance: str

    # 5. Attributions, Guards & Challenges
    group_scores: dict[str, float]
    challenge_breakdown: dict[str, int]
    double_counting_adjustments: dict[str, float]
    structural_adjustments: dict[str, float]
    method_version: str = "ValuationBridgeV2"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ValuationBridgeV2:
    """
    Bridges Guard G qualitative features and advisory challenges into DCF valuation adjustments
    under strict dual-track accounting and double-counting protection.
    """

    FEATURE_GROUPS = {
        "growth": (
            [
                "demand_momentum",
                "customer_adoption",
                "inference_demand",
                "product_cycle_strength",
            ],
            0.35,
        ),
        "headwinds": (
            [
                "supply_constraint",
                "china_outlook",
                "export_control_outlook",
                "competition_outlook",
                "customer_concentration_outlook",
            ],
            0.30,
        ),
        "moat": (
            [
                "pricing_power",
                "ecosystem_strength",
                "moat_strength_signal",
                "switching_cost_strength",
                "margin_outlook",
                "custom_asic_outlook",
            ],
            0.20,
        ),
        "quality": (
            [
                "customer_financing_quality",
                "working_capital_quality",
                "inventory_quality",
                "management_credibility_signal",
                "guidance_visibility",
            ],
            0.15,
        ),
    }

    def __init__(
        self,
        ai_sensitivity: float = 0.35,
        haircut_per_downside: float = 0.02,
        bonus_per_upside: float = 0.015,
    ) -> None:
        self.ai_sensitivity = ai_sensitivity
        self.haircut_per_downside = haircut_per_downside
        self.bonus_per_upside = bonus_per_upside

    def compute_composite_score(
        self,
        features: dict[str, tuple[float, float]],
        overrides: dict[str, float] | None = None,
        guidance_revenue_revision: float = 0.0,
        return_adjustments: bool = False,
    ) -> Any:
        """
        Compute weighted qualitative score across 4 fundamental dimensions.
        Includes Double-Counting Guard when guidance revision is positive.
        """
        overrides = overrides or {}
        group_scores: dict[str, float] = {}
        double_counting_adjustments: dict[str, float] = {}
        weighted_sum = 0.0
        total_weight = 0.0

        # Double-counting mitigation factor
        # If guidance revenue revision > 0, dampen positive growth features by up to 50%
        growth_dampener = 1.0
        if guidance_revenue_revision > 0.0:
            growth_dampener = max(0.5, 1.0 - min(0.5, guidance_revenue_revision))
            double_counting_adjustments["guidance_revenue_revision"] = round(
                guidance_revenue_revision, 4
            )
            double_counting_adjustments["growth_feature_dampener"] = round(growth_dampener, 4)

        for group_name, (keys, weight) in self.FEATURE_GROUPS.items():
            vals: list[float] = []
            for k in keys:
                if k in overrides:
                    val = float(overrides[k])
                elif k in features:
                    raw_val, conf = features[k]
                    val = float(raw_val) * float(conf)
                else:
                    continue

                # Apply double-counting guard to positive growth signals
                if group_name == "growth" and val > 0.0 and growth_dampener < 1.0:
                    original_val = val
                    val = val * growth_dampener
                    double_counting_adjustments[f"damped_{k}"] = round(original_val - val, 4)

                vals.append(val)

            if vals:
                g_score = sum(vals) / len(vals)
                group_scores[group_name] = round(g_score, 4)
                weighted_sum += g_score * weight
                total_weight += weight
            else:
                group_scores[group_name] = 0.0

        composite = weighted_sum / total_weight if total_weight > 0 else 0.0
        # Clamp to [-1.0, 1.0]
        composite = max(-1.0, min(1.0, composite))
        if return_adjustments:
            return round(composite, 4), group_scores, double_counting_adjustments
        return round(composite, 4), group_scores

    def compute_challenge_haircut(
        self, challenges: list[dict[str, Any]]
    ) -> tuple[float, dict[str, int]]:
        """Calculate tail-risk haircut based on grounded advisory challenges."""
        upsides = 0
        downsides = 0
        monitors = 0

        for ch in challenges:
            kind = ch.get("kind", "").lower()
            direction = ch.get("direction", "").lower()
            if kind == "upside" or direction == "up":
                upsides += 1
            elif kind in ("downside", "anomaly") or direction == "down":
                downsides += 1
            else:
                monitors += 1

        # Calculate haircut bounded within [0.70, 1.15]
        net_adjustment = (self.bonus_per_upside * upsides) - (self.haircut_per_downside * downsides)
        haircut = max(0.70, min(1.15, 1.0 + net_adjustment))

        breakdown = {
            "upsides": upsides,
            "downsides": downsides,
            "monitors": monitors,
            "total": len(challenges),
        }
        return round(haircut, 4), breakdown

    def evaluate(
        self,
        quarter: str,
        as_of_date: str,
        market_price: float,
        quant_dcf_base: float,
        features: dict[str, tuple[float, float]],
        challenges: list[dict[str, Any]],
        overrides: dict[str, float] | None = None,
        market_implied_growth_rate: float | None = None,
        quant_forecast_growth_rate: float | None = None,
        guidance_revenue_revision: float = 0.0,
    ) -> ValuationBridgeResult:
        """
        Bridge quantitative DCF with qualitative signals to generate dual-track fair value channels.
        """
        composite_score, group_scores, dc_adjustments = self.compute_composite_score(
            features,
            overrides,
            guidance_revenue_revision=guidance_revenue_revision,
            return_adjustments=True,
        )
        haircut, challenge_breakdown = self.compute_challenge_haircut(challenges)

        # 1. Quant Baseline Expectations Gap (Pure quantitative)
        quant_gap = (quant_dcf_base - market_price) / market_price if market_price > 0 else 0.0

        # 2. Structural Parameter Attribution
        # Moat reduces WACC (-0.5% per 1.0 moat score), Headwinds increase WACC (+0.7% per 1.0 headwind score)
        wacc_adjustment_bp = (-50.0 * group_scores.get("moat", 0.0)) + (
            70.0 * max(0.0, -group_scores.get("headwinds", 0.0))
        )
        growth_adjustment_bp = 150.0 * group_scores.get("growth", 0.0)
        structural_adjustments = {
            "wacc_delta_basis_points": round(wacc_adjustment_bp, 1),
            "growth_delta_basis_points": round(growth_adjustment_bp, 1),
            "tail_risk_discount_pct": round((1.0 - haircut) * 100.0, 2),
        }

        # 3. AI-adjusted fair value
        ai_base = quant_dcf_base * (1.0 + self.ai_sensitivity * composite_score) * haircut

        # Scenario bands
        ai_bull = ai_base * 1.25 * (1.0 + 0.10 * max(0.0, composite_score))
        ai_bear = ai_base * 0.75 * (1.0 - 0.10 * max(0.0, -composite_score))
        ai_stress = ai_bear * 0.85

        # AI expectations gap
        ai_gap = (ai_base - market_price) / market_price if market_price > 0 else 0.0

        if ai_gap > 0.15:
            stance = "UNDERVALUED"
        elif ai_gap >= -0.10:
            stance = "FAIRLY_VALUED"
        else:
            stance = "OVERVALUED"

        return ValuationBridgeResult(
            quarter=quarter,
            as_of_date=as_of_date,
            market_price=round(market_price, 2),
            quant_dcf_base=round(quant_dcf_base, 2),
            quant_expectations_gap=round(quant_gap, 4),
            market_implied_growth_rate=round(market_implied_growth_rate, 4)
            if market_implied_growth_rate is not None
            else None,
            quant_forecast_growth_rate=round(quant_forecast_growth_rate, 4)
            if quant_forecast_growth_rate is not None
            else None,
            ai_composite_score=round(composite_score, 4),
            tail_risk_haircut=round(haircut, 4),
            ai_fair_value_base=round(ai_base, 2),
            ai_fair_value_bull=round(ai_bull, 2),
            ai_fair_value_bear=round(ai_bear, 2),
            ai_fair_value_stress=round(ai_stress, 2),
            expectations_gap=round(ai_gap, 4),
            ai_expectations_gap=round(ai_gap, 4),
            valuation_stance=stance,
            group_scores=group_scores,
            challenge_breakdown=challenge_breakdown,
            double_counting_adjustments=dc_adjustments,
            structural_adjustments=structural_adjustments,
            method_version="ValuationBridgeV2",
        )


# Backward compatibility alias
ValuationBridgeV1 = ValuationBridgeV2
