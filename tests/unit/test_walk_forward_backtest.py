"""
Unit tests for StockOS Walk-Forward Backtester Engine (WalkForwardBacktester).
"""

from pathlib import Path
import pytest

from valuation_engine.backtest.walk_forward import (
    BacktestConfig,
    BuyAndHoldPolicy,
    NaiveDCFPolicy,
    ValuationBridgeAlphaPolicy,
    ValuationGrowthOverlayPolicy,
    WalkForwardBacktester,
)


def test_growth_overlay_policy_mapping():
    policy = ValuationGrowthOverlayPolicy()

    # Gap >= +5% -> 1.0
    d1 = policy.decide({"expectations_gap": 0.08, "valuation_stance": "FAIRLY_VALUED"})
    assert d1.equity_weight == 1.0

    # Gap -10% -> 0.85
    d2 = policy.decide({"expectations_gap": -0.10, "valuation_stance": "FAIRLY_VALUED"})
    assert d2.equity_weight == 0.85

    # Gap -20% -> 0.60
    d3 = policy.decide({"expectations_gap": -0.20, "valuation_stance": "OVERVALUED"})
    assert d3.equity_weight == 0.60

    # Gap -40% -> 0.40 core
    d4 = policy.decide({"expectations_gap": -0.40, "valuation_stance": "OVERVALUED"})
    assert d4.equity_weight == 0.40
    assert d4.cash_weight == 0.60


def test_alpha_policy_mapping():
    policy = ValuationBridgeAlphaPolicy()

    # 1. Undervalued (Gap >= +5%)
    dec_undervalued = policy.decide({
        "quarter": "FY2027-Q2",
        "as_of_date": "2026-08-27",
        "expectations_gap": 0.0735,
        "valuation_stance": "FAIRLY_VALUED",
        "challenge_breakdown": {"downsides": 2},
    })
    assert dec_undervalued.action == "BUY"
    assert dec_undervalued.equity_weight == 1.0
    assert dec_undervalued.cash_weight == 0.0

    # 2. Fairly valued with few downside challenges (<=4)
    dec_fair_low_risk = policy.decide({
        "quarter": "FY2027-Q2",
        "as_of_date": "2026-08-27",
        "expectations_gap": -0.05,
        "valuation_stance": "FAIRLY_VALUED",
        "challenge_breakdown": {"downsides": 3},
    })
    assert dec_fair_low_risk.equity_weight == 1.0
    assert dec_fair_low_risk.cash_weight == 0.0

    # 3. Fairly valued with high downside challenges (>4)
    dec_fair_high_risk = policy.decide({
        "quarter": "FY2026-Q1",
        "as_of_date": "2025-05-29",
        "expectations_gap": -0.10,
        "valuation_stance": "FAIRLY_VALUED",
        "challenge_breakdown": {"downsides": 5},
    })
    assert dec_fair_high_risk.equity_weight == 0.70
    assert dec_fair_high_risk.cash_weight == 0.30

    # 4. Overvalued / Trim (-30% <= Gap < -15%)
    dec_overvalued = policy.decide({
        "quarter": "FY2025-Q4",
        "as_of_date": "2025-02-27",
        "expectations_gap": -0.186,
        "valuation_stance": "OVERVALUED",
        "challenge_breakdown": {"downsides": 4},
    })
    assert dec_overvalued.action == "TRIM"
    assert dec_overvalued.equity_weight == 0.35
    assert dec_overvalued.cash_weight == 0.65

    # 5. Severe bubble / Capital preservation (Gap < -30%)
    dec_bubble = policy.decide({
        "quarter": "FY2023-Q2",
        "as_of_date": "2022-08-25",
        "expectations_gap": -0.5767,
        "valuation_stance": "OVERVALUED",
        "challenge_breakdown": {"downsides": 5},
    })
    assert dec_bubble.action == "CAPITAL_PRESERVATION"
    assert dec_bubble.equity_weight == 0.0
    assert dec_bubble.cash_weight == 1.0


def test_naive_dcf_policy_mapping():
    policy = NaiveDCFPolicy()

    # Buy when DCF is higher than price
    d1 = policy.decide({
        "quarter": "Q1",
        "as_of_date": "2024-01-01",
        "market_price": 100.0,
        "quant_dcf_base": 120.0,
    })
    assert d1.equity_weight == 1.0

    # Sell when DCF is far below price
    d2 = policy.decide({
        "quarter": "Q2",
        "as_of_date": "2024-04-01",
        "market_price": 200.0,
        "quant_dcf_base": 100.0,
    })
    assert d2.equity_weight == 0.0
    assert d2.cash_weight == 1.0


def test_buy_and_hold_policy():
    policy = BuyAndHoldPolicy()
    d = policy.decide({"quarter": "Q1", "as_of_date": "2024-01-01"})
    assert d.equity_weight == 1.0
    assert d.cash_weight == 0.0


def test_backtester_nav_accounting_synthetic(monkeypatch):
    backtester = WalkForwardBacktester(
        config=BacktestConfig(
            initial_capital=10_000.0,
            annual_risk_free_rate=0.04,
            transaction_cost_bps=10.0,
        )
    )

    synthetic_bars = [
        {"date": "2024-01-02", "open": 100.0, "high": 105.0, "low": 98.0, "close": 102.0, "adj_close": 102.0, "volume": 1000},
        {"date": "2024-01-03", "open": 102.0, "high": 106.0, "low": 101.0, "close": 105.0, "adj_close": 105.0, "volume": 1200},
        {"date": "2024-02-01", "open": 110.0, "high": 115.0, "low": 108.0, "close": 112.0, "adj_close": 112.0, "volume": 1500},
        {"date": "2024-02-02", "open": 112.0, "high": 118.0, "low": 110.0, "close": 115.0, "adj_close": 115.0, "volume": 1600},
    ]

    monkeypatch.setattr(backtester, "load_daily_prices", lambda **kwargs: synthetic_bars)

    manifest_data = {
        "panel_quarters": {
            "Q1": {
                "quarter": "Q1",
                "as_of_date": "2024-01-02",
                "signal_available_at": "2024-01-02T09:00:00-05:00",
                "market_price": 100.0,
                "quant_dcf_base": 120.0,
                "expectations_gap": 0.20,
                "valuation_stance": "UNDERVALUED",
                "challenge_breakdown": {"downsides": 1},
            },
            "Q2": {
                "quarter": "Q2",
                "as_of_date": "2024-02-01",
                "signal_available_at": "2024-02-01T09:00:00-05:00",
                "market_price": 110.0,
                "quant_dcf_base": 115.0,
                "expectations_gap": 0.05,
                "valuation_stance": "FAIRLY_VALUED",
                "challenge_breakdown": {"downsides": 2},
            },
        }
    }

    report = backtester.run(
        manifest_data=manifest_data,
        policy=ValuationBridgeAlphaPolicy(),
        strategy_name="SyntheticTest",
    )

    assert report.strategy_name == "SyntheticTest"
    assert report.initial_capital == 10_000.0
    assert report.final_nav > 10_000.0
    assert len(report.period_results) == 2
    assert len(report.daily_equity_curve) == 4
    assert report.max_drawdown <= 0.0


def test_backtester_real_db_manifest_run():
    import json
    root = Path(__file__).resolve().parent.parent.parent
    manifest_path = root / "data/m41/fsi/cohort/receipts/valuation_bridge_manifest.json"
    db_path = root / "data/qve.db"

    if not manifest_path.exists() or not db_path.exists():
        pytest.skip("Manifest or qve.db missing for full backtest integration.")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    backtester = WalkForwardBacktester(db_path=db_path)
    report = backtester.run(manifest_data=manifest, policy=ValuationBridgeAlphaPolicy())

    assert report.strategy_name == "ValuationBridgeAlphaPolicy"
    assert len(report.period_results) == 7
    assert len(report.daily_equity_curve) > 900
    assert report.final_nav > 0
    assert -1.0 <= report.max_drawdown <= 0.0
