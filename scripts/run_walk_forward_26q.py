#!/usr/bin/env python3
"""
StockOS 26-Quarter Long-Horizon Walk-Forward Backtester Runner.
Executes multi-strategy PIT backtesting on the complete 26-quarter panel (2020-05-22 to 2026-09-11),
comparing AI Valuation Bridge against Naive DCF, Fixed 40/60 Allocation, and Buy-and-Hold benchmark.
Outputs walk_forward_backtest_26q_receipt.json.
"""

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from valuation_engine.backtest.walk_forward import (
    BacktestConfig,
    BuyAndHoldPolicy,
    FixedAllocationPolicy,
    NaiveDCFPolicy,
    ValuationBridgeAlphaPolicy,
    ValuationGrowthOverlayPolicy,
    WalkForwardBacktester,
)

MANIFEST_26Q_PATH = ROOT / "data/m41/fsi/cohort/receipts/valuation_bridge_manifest_26q.json"
QVE_DB_PATH = ROOT / "data/qve.db"
RECEIPT_26Q_PATH = ROOT / "data/m41/fsi/cohort/receipts/walk_forward_backtest_26q_receipt.json"


def run_walk_forward_26q():
    print("==========================================================================")
    print(" StockOS P1: 26-Quarter Long-Horizon Walk-Forward Backtest (2020 ~ 2026)")
    print("==========================================================================")

    if not MANIFEST_26Q_PATH.exists():
        raise FileNotFoundError(f"Manifest not found: {MANIFEST_26Q_PATH}")

    with open(MANIFEST_26Q_PATH, encoding="utf-8") as f:
        manifest = json.load(f)

    config = BacktestConfig(
        initial_capital=100_000.0,
        annual_risk_free_rate=0.04,  # 4.0% SOFR
        transaction_cost_bps=10.0,   # 10 bps
        benchmark_ticker="NVDA",
    )

    backtester = WalkForwardBacktester(config=config, db_path=QVE_DB_PATH)

    print("\n1. Running Strategy 1: ValuationBridgeAlphaPolicy (AI 估值橋接保本型策略)...")
    ai_report = backtester.run(
        manifest_data=manifest,
        policy=ValuationBridgeAlphaPolicy(),
        strategy_name="ValuationBridgeAlphaPolicy",
    )
    print(f"   ✓ Final NAV: ${ai_report.final_nav:,.2f} | Total Return: {ai_report.cumulative_return*100:+.1f}% | CAGR: {ai_report.cagr*100:.1f}% | Sharpe: {ai_report.sharpe_ratio:.2f} | MDD: {ai_report.max_drawdown*100:.1f}%")

    print("\n2. Running Strategy 2: ValuationGrowthOverlayPolicy (AI 成長平衡增益型策略)...")
    growth_report = backtester.run(
        manifest_data=manifest,
        policy=ValuationGrowthOverlayPolicy(),
        strategy_name="ValuationGrowthOverlayPolicy",
    )
    print(f"   ✓ Final NAV: ${growth_report.final_nav:,.2f} | Total Return: {growth_report.cumulative_return*100:+.1f}% | CAGR: {growth_report.cagr*100:.1f}% | Sharpe: {growth_report.sharpe_ratio:.2f} | MDD: {growth_report.max_drawdown*100:.1f}%")

    print("\n3. Running Strategy 3: FixedAllocationPolicy (消融對照組: 固定 40% 股票 / 60% 現金)...")
    fixed_report = backtester.run(
        manifest_data=manifest,
        policy=FixedAllocationPolicy(target_equity_weight=0.40),
        strategy_name="Fixed40EquityBenchmark",
    )
    print(f"   ✓ Final NAV: ${fixed_report.final_nav:,.2f} | Total Return: {fixed_report.cumulative_return*100:+.1f}% | CAGR: {fixed_report.cagr*100:.1f}% | Sharpe: {fixed_report.sharpe_ratio:.2f} | MDD: {fixed_report.max_drawdown*100:.1f}%")

    print("\n4. Running Strategy 4: NaiveDCFPolicy (純量化 DCF 基準)...")
    naive_report = backtester.run(
        manifest_data=manifest,
        policy=NaiveDCFPolicy(),
        strategy_name="NaiveDCFPolicy",
    )
    print(f"   ✓ Final NAV: ${naive_report.final_nav:,.2f} | Total Return: {naive_report.cumulative_return*100:+.1f}% | CAGR: {naive_report.cagr*100:.1f}% | Sharpe: {naive_report.sharpe_ratio:.2f} | MDD: {naive_report.max_drawdown*100:.1f}%")

    print("\n5. Running Strategy 5: BuyAndHoldPolicy (被動長期持有基準)...")
    bh_report = backtester.run(
        manifest_data=manifest,
        policy=BuyAndHoldPolicy(),
        strategy_name="BuyAndHoldPolicy",
    )
    print(f"   ✓ Final NAV: ${bh_report.final_nav:,.2f} | Total Return: {bh_report.cumulative_return*100:+.1f}% | CAGR: {bh_report.cagr*100:.1f}% | Sharpe: {bh_report.sharpe_ratio:.2f} | MDD: {bh_report.max_drawdown*100:.1f}%")

    # Long-horizon ablation attribution
    ablation_attribution = {
        "beta_reduction_mdd_impact_pct": round((fixed_report.max_drawdown - bh_report.max_drawdown) * 100.0, 2),
        "active_timing_cagr_pct": round((growth_report.cagr - fixed_report.cagr) * 100.0, 2),
        "ai_incremental_sharpe": round(growth_report.sharpe_ratio - naive_report.sharpe_ratio, 2),
        "ai_incremental_cagr_pct": round((growth_report.cagr - naive_report.cagr) * 100.0, 2),
        "total_rebalances": len(ai_report.period_results),
        "total_trading_days": len(ai_report.daily_equity_curve),
    }

    receipt = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": asdict(config),
        "panel_total_quarters": len(manifest.get("panel_quarters", {})),
        "ablation_attribution": ablation_attribution,
        "comparison_summary": [
            {
                "strategy_name": "AI 估值橋接保本型 (Conservative)",
                "final_nav": ai_report.final_nav,
                "cumulative_return": ai_report.cumulative_return,
                "cagr": ai_report.cagr,
                "annualized_volatility": ai_report.annualized_volatility,
                "sharpe_ratio": ai_report.sharpe_ratio,
                "max_drawdown": ai_report.max_drawdown,
                "calmar_ratio": ai_report.calmar_ratio,
                "win_rate": ai_report.win_rate,
                "alpha": ai_report.alpha,
                "beta": ai_report.beta,
            },
            {
                "strategy_name": "AI 成長平衡增益型 (Growth Overlay)",
                "final_nav": growth_report.final_nav,
                "cumulative_return": growth_report.cumulative_return,
                "cagr": growth_report.cagr,
                "annualized_volatility": growth_report.annualized_volatility,
                "sharpe_ratio": growth_report.sharpe_ratio,
                "max_drawdown": growth_report.max_drawdown,
                "calmar_ratio": growth_report.calmar_ratio,
                "win_rate": growth_report.win_rate,
                "alpha": growth_report.alpha,
                "beta": growth_report.beta,
            },
            {
                "strategy_name": "固定配置消融組 (Fixed 40% NVDA / 60% Cash)",
                "final_nav": fixed_report.final_nav,
                "cumulative_return": fixed_report.cumulative_return,
                "cagr": fixed_report.cagr,
                "annualized_volatility": fixed_report.annualized_volatility,
                "sharpe_ratio": fixed_report.sharpe_ratio,
                "max_drawdown": fixed_report.max_drawdown,
                "calmar_ratio": fixed_report.calmar_ratio,
                "win_rate": fixed_report.win_rate,
                "alpha": fixed_report.alpha,
                "beta": fixed_report.beta,
            },
            {
                "strategy_name": "純量化 DCF 基準 (Naive DCF)",
                "final_nav": naive_report.final_nav,
                "cumulative_return": naive_report.cumulative_return,
                "cagr": naive_report.cagr,
                "annualized_volatility": naive_report.annualized_volatility,
                "sharpe_ratio": naive_report.sharpe_ratio,
                "max_drawdown": naive_report.max_drawdown,
                "calmar_ratio": naive_report.calmar_ratio,
                "win_rate": naive_report.win_rate,
                "alpha": naive_report.alpha,
                "beta": naive_report.beta,
            },
            {
                "strategy_name": "被動持有基準 (Buy & Hold NVDA)",
                "final_nav": bh_report.final_nav,
                "cumulative_return": bh_report.cumulative_return,
                "cagr": bh_report.cagr,
                "annualized_volatility": bh_report.annualized_volatility,
                "sharpe_ratio": bh_report.sharpe_ratio,
                "max_drawdown": bh_report.max_drawdown,
                "calmar_ratio": bh_report.calmar_ratio,
                "win_rate": bh_report.win_rate,
                "alpha": 0.0,
                "beta": 1.0,
            },
        ],
        "strategies": {
            "ai_conservative": asdict(ai_report),
            "ai_growth_overlay": asdict(growth_report),
            "fixed_40_equity": asdict(fixed_report),
            "naive_dcf": asdict(naive_report),
            "buy_and_hold": asdict(bh_report),
        },
    }

    RECEIPT_26Q_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RECEIPT_26Q_PATH, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)

    print("\n==========================================================================")
    print(f"✓ 26-Quarter Walk-forward backtest receipt written to: {RECEIPT_26Q_PATH}")
    print("==========================================================================")

    # Print executive comparison table
    print(f"\n📊 26 季全歷史長週期回測對照總表 (26 次調倉, {len(ai_report.daily_equity_curve)} 個交易日):")
    print(f"{'策略名稱':<36} | {'期末淨值':<12} | {'累積報酬':<10} | {'CAGR':<8} | {'波動度':<8} | {'Sharpe':<6} | {'MDD':<8} | {'Alpha':<8}")
    print("-" * 115)
    for s in receipt["comparison_summary"]:
        print(
            f"{s['strategy_name']:<36} | "
            f"${s['final_nav']:>11,.0f} | "
            f"{s['cumulative_return']*100:>9.1f}% | "
            f"{s['cagr']*100:>7.1f}% | "
            f"{s['annualized_volatility']*100:>7.1f}% | "
            f"{s['sharpe_ratio']:>6.2f} | "
            f"{s['max_drawdown']*100:>7.1f}% | "
            f"{s['alpha']*100:>7.1f}%"
        )
    print("==========================================================================")
    print("\n🔍 26 季全週期消融歸因分析 (Ablation Attribution):")
    print(f"  • 固定降低 Beta / 40% 倉位之 MDD 改善幅度: {ablation_attribution['beta_reduction_mdd_impact_pct']:+.1f}%")
    print(f"  • AI 動態擇時相比固定 40% 倉位之增益 CAGR: {ablation_attribution['active_timing_cagr_pct']:+.1f}%")
    print(f"  • AI 質化橋接相比純量化 Naive DCF 增量 Sharpe: {ablation_attribution['ai_incremental_sharpe']:+.2f}")
    print(f"  • AI 質化橋接相比純量化 Naive DCF 增量 CAGR: {ablation_attribution['ai_incremental_cagr_pct']:+.1f}%")
    print("==========================================================================")


if __name__ == "__main__":
    run_walk_forward_26q()
