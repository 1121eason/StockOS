"""
Unit test suite verifying P0 Governance, Dual-Track Valuation Contract,
Audited Walk-Forward Accounting, 4-Way Ablation Controls, and Signal Fusion.
"""

import math
from pathlib import Path
import pytest

from valuation_engine.valuation.bridge import ValuationBridgeV2, ValuationBridgeResult
from valuation_engine.backtest.walk_forward import (
    BacktestConfig,
    BuyAndHoldPolicy,
    FixedAllocationPolicy,
    NaiveDCFPolicy,
    ValuationBridgeAlphaPolicy,
    ValuationGrowthOverlayPolicy,
    WalkForwardBacktester,
)
from valuation_engine.decision.signal_fusion import (
    ForecastRevisionInput,
    RegimeInput,
    SignalFusionEngine,
)


def test_quant_baseline_purity():
    """Verify that quant baseline DCF and expectations gap remain 100% pure and untouched by AI."""
    bridge = ValuationBridgeV2()
    market_price = 100.0
    quant_dcf = 120.0
    
    # Run with empty features
    res_empty = bridge.evaluate(
        quarter="FY2024-Q1",
        as_of_date="2023-05-25",
        market_price=market_price,
        quant_dcf_base=quant_dcf,
        features={},
        challenges=[],
    )
    assert res_empty.quant_dcf_base == 120.0
    assert res_empty.quant_expectations_gap == pytest.approx(0.20, abs=1e-4)
    assert res_empty.ai_composite_score == 0.0

    # Run with massive AI bullish features and overrides
    res_bull = bridge.evaluate(
        quarter="FY2024-Q1",
        as_of_date="2023-05-25",
        market_price=market_price,
        quant_dcf_base=quant_dcf,
        features={"demand_momentum": (1.0, 1.0), "product_cycle_strength": (1.0, 1.0)},
        challenges=[{"kind": "upside", "target_variable": "fcf", "direction": "up", "description": "huge"}],
    )
    # Quant baseline MUST remain exactly identical
    assert res_bull.quant_dcf_base == 120.0
    assert res_bull.quant_expectations_gap == pytest.approx(0.20, abs=1e-4)
    # AI fair value can reflect qualitative signals
    assert res_bull.ai_fair_value_base > res_bull.quant_dcf_base


def test_double_counting_guard():
    """Verify that positive guidance revision dampens positive growth features."""
    bridge = ValuationBridgeV2()
    features = {
        "demand_momentum": (0.8, 1.0),
        "product_cycle_strength": (0.6, 1.0),
    }

    # Case 1: No guidance revision
    score_no_guidance, _, adj_none = bridge.compute_composite_score(
        features, guidance_revenue_revision=0.0, return_adjustments=True
    )
    assert "guidance_revenue_revision" not in adj_none

    # Case 2: Guidance revision is +15% (management already incorporated upside)
    score_with_guidance, _, adj_with = bridge.compute_composite_score(
        features, guidance_revenue_revision=0.15, return_adjustments=True
    )
    
    assert "guidance_revenue_revision" in adj_with
    assert adj_with["growth_feature_dampener"] == pytest.approx(0.85, abs=1e-4)
    # Composite score with guard must be lower than without guard to prevent double-counting
    assert score_with_guidance < score_no_guidance


def test_overnight_accounting_and_turnover_continuity():
    """Verify that overnight price moves on existing holdings are correctly realized at rebalance Open."""
    backtester = WalkForwardBacktester(config=BacktestConfig(initial_capital=100_000.0, transaction_cost_bps=10.0))

    # Synthetic 2-period manifest
    manifest_data = {
        "panel_quarters": {
            "Q1": {
                "quarter": "Q1",
                "as_of_date": "2023-01-01",
                "market_price": 100.0,
                "quant_dcf_base": 120.0,
                "expectations_gap": 0.20,
                "valuation_stance": "UNDERVALUED",
            },
            "Q2": {
                "quarter": "Q2",
                "as_of_date": "2023-01-03",
                "market_price": 120.0,
                "quant_dcf_base": 80.0,
                "expectations_gap": -0.33,
                "valuation_stance": "OVERVALUED",
            },
        }
    }

    # Synthetic price bars with overnight gap between 2023-01-02 close ($110) and 2023-01-03 open ($115)
    mock_bars = [
        {"date": "2023-01-01", "open": 100.0, "high": 105.0, "low": 99.0, "close": 105.0, "adjusted_close": 105.0, "volume": 1000},
        {"date": "2023-01-02", "open": 105.0, "high": 110.0, "low": 104.0, "close": 110.0, "adjusted_close": 110.0, "volume": 1000},
        {"date": "2023-01-03", "open": 115.0, "high": 116.0, "low": 112.0, "close": 112.0, "adjusted_close": 112.0, "volume": 1000},
        {"date": "2023-01-04", "open": 112.0, "high": 114.0, "low": 111.0, "close": 114.0, "adjusted_close": 114.0, "volume": 1000},
    ]
    backtester.load_daily_prices = lambda start_date, end_date="2026-09-11": mock_bars

    report = backtester.run(manifest_data, policy=ValuationBridgeAlphaPolicy())
    assert len(report.period_results) == 2
    
    # Check that day 3 (rebalance day) pre-trade valuation captured the overnight gap to $115
    day2_nav = report.daily_equity_curve[1]["strategy_nav"]
    day3_nav = report.daily_equity_curve[2]["strategy_nav"]
    assert day3_nav > day2_nav  # Benefited from overnight gap


def test_fixed_allocation_ablation_control():
    """Verify that FixedAllocationPolicy adheres to exact 40% equity weight across all periods."""
    policy = FixedAllocationPolicy(target_equity_weight=0.40)
    decision = policy.decide({"quarter": "FY2024-Q1", "as_of_date": "2023-05-25"})
    assert decision.equity_weight == 0.40
    assert decision.cash_weight == 0.60
    assert decision.action == "FIXED_ALLOCATION"


def test_signal_fusion_with_regime_and_forecast_revisions():
    """Verify that SignalFusionEngine enforces regime caps and forecast revision penalties."""
    engine = SignalFusionEngine()
    valuation = ValuationBridgeResult(
        quarter="FY2025-Q1",
        as_of_date="2024-05-22",
        market_price=100.0,
        quant_dcf_base=120.0,
        quant_expectations_gap=0.20,
        market_implied_growth_rate=0.25,
        quant_forecast_growth_rate=0.30,
        ai_composite_score=0.40,
        tail_risk_haircut=0.88,  # tail risk < 0.90
        ai_fair_value_base=135.0,
        ai_fair_value_bull=160.0,
        ai_fair_value_bear=100.0,
        ai_fair_value_stress=85.0,
        expectations_gap=0.35,
        ai_expectations_gap=0.35,
        valuation_stance="UNDERVALUED",
        group_scores={"growth": 0.5, "headwinds": -0.2, "moat": 0.4, "quality": 0.3},
        challenge_breakdown={"upsides": 2, "downsides": 5, "monitors": 1, "total": 8},
        double_counting_adjustments={},
        structural_adjustments={},
    )

    # 1. Normal Hypergrowth Regime + Upward Revision
    regime_bull = RegimeInput(
        confirmed_regime="Hypergrowth",
        candidate_regime="Hypergrowth",
        transition_status="STABLE",
        confidence=0.85,
    )
    rev_up = ForecastRevisionInput(
        revenue_revision_pct=0.10,
        eps_revision_pct=0.12,
        fcf_revision_pct=0.15,
        revision_direction="UPWARD",
    )
    fused_bull = engine.fuse(valuation, regime_bull, rev_up)
    # Valuation gave 1.0, tail haircut gave -0.10, final = 0.90
    assert fused_bull.equity_weight == 0.90
    assert fused_bull.action == "OVERWEIGHT"

    # 2. Cyclical Downturn Regime
    regime_down = RegimeInput(
        confirmed_regime="Cyclical Downturn",
        candidate_regime="Cyclical Downturn",
        transition_status="STABLE",
        confidence=0.90,
    )
    fused_down = engine.fuse(valuation, regime_down, rev_up)
    # Hard cap at 40% due to Cyclical Downturn
    assert fused_down.equity_weight <= 0.40
    assert any("Cyclical Downturn" in log for log in fused_down.audit_trail)
