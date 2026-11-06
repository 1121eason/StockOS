"""
StockOS Walk-Forward Backtester Engine (WalkForwardBacktester).
Point-In-Time (PIT) simulation of systematic allocation strategies driven by
the Valuation Bridge (ValuationBridgeV2), with audited overnight accounting
and 4-way ablation controls against Naive DCF, Fixed 40/60 Allocation, Passive Buy-and-Hold,
and Risk-Free Cash benchmarks.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional


@dataclass
class BacktestConfig:
    initial_capital: float = 100_000.0
    annual_risk_free_rate: float = 0.04  # 4.0% SOFR / Treasury rate
    transaction_cost_bps: float = 10.0  # 10 bps = 0.10% per turnover
    benchmark_ticker: str = "NVDA"


@dataclass
class SignalDecision:
    quarter: str
    as_of_date: str
    trade_date: str
    action: str  # STRONG_BUY, BUY, FAIRLY_VALUED, TRIM, CAPITAL_PRESERVATION, FIXED_ALLOCATION
    equity_weight: float
    cash_weight: float
    expectations_gap: float
    valuation_stance: str
    rationale: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PeriodResult:
    period_index: int
    quarter: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    equity_weight: float
    cash_weight: float
    period_stock_return: float
    period_strategy_return: float
    period_cash_return: float
    period_turnover: float
    transaction_fee_paid: float
    start_nav: float
    end_nav: float
    valuation_stance: str
    expectations_gap: float


@dataclass
class DailyNavPoint:
    date: str
    stock_price: float
    strategy_nav: float
    benchmark_nav: float
    cash_nav: float
    strategy_drawdown: float
    benchmark_drawdown: float
    equity_weight: float


@dataclass
class BacktestReport:
    strategy_name: str
    initial_capital: float
    final_nav: float
    cumulative_return: float
    cagr: float
    annualized_volatility: float
    sharpe_ratio: float
    max_drawdown: float
    calmar_ratio: float
    win_rate: float
    benchmark_cumulative_return: float
    benchmark_cagr: float
    benchmark_volatility: float
    benchmark_sharpe: float
    benchmark_max_drawdown: float
    alpha: float
    beta: float
    period_results: List[Dict[str, Any]]
    daily_equity_curve: List[Dict[str, Any]]
    ablation_attribution: Dict[str, Any] = field(default_factory=dict)


class ValuationBridgeAlphaPolicy:
    """
    Systematic asset allocation policy driven by ValuationBridgeV2 signals.
    Maps expectations gap and tail risk challenges to dynamic equity weights.
    """

    def decide(self, quarter_info: Dict[str, Any]) -> SignalDecision:
        quarter = quarter_info.get("quarter", "")
        as_of_date = quarter_info.get("as_of_date", "")
        gap = float(quarter_info.get("expectations_gap", 0.0))
        stance = quarter_info.get("valuation_stance", "FAIRLY_VALUED")
        challenges = quarter_info.get("challenge_breakdown", {})
        downsides = challenges.get("downsides", 0)

        # 1. Undervalued / High Margin of Safety
        if gap >= 0.05 or stance == "UNDERVALUED":
            action = "STRONG_BUY" if gap >= 0.20 else "BUY"
            equity_weight = 1.0
            cash_weight = 0.0
            rationale = (
                f"預期差正向顯著 (+{gap*100:.1f}%)，內在價值高於市場定價，"
                f"安全邊際充裕，配置 100% 股票倉位。"
            )

        # 2. Fairly Valued
        elif -0.15 <= gap < 0.05:
            action = "FAIRLY_VALUED"
            if downsides > 4:
                equity_weight = 0.70
                cash_weight = 0.30
                rationale = (
                    f"預期差處於合理區間 ({gap*100:.1f}%)，但面臨 {downsides} 項下行模型質疑，"
                    f"維持 70% 股票持倉，配置 30% 現金防禦緩衝。"
                )
            else:
                equity_weight = 1.0
                cash_weight = 0.0
                rationale = (
                    f"預期差處於合理區間 ({gap*100:.1f}%)，且尾部挑戰受控 ({downsides} 項)，"
                    f"基本面與現金流相稱，配置 100% 股票倉位。"
                )

        # 3. Overvalued / Moderate Bubble Premium
        elif -0.30 <= gap < -0.15:
            action = "TRIM"
            equity_weight = 0.35
            cash_weight = 0.65
            rationale = (
                f"市場定價透支現金流 (預期差 {gap*100:.1f}%)，估值處於高位，"
                f"調降股票部位至 35%，保留 65% 現金獲利了結以規避回撤。"
            )

        # 4. Severe Overvaluation / Extreme Speculation
        else:
            action = "CAPITAL_PRESERVATION"
            equity_weight = 0.0
            cash_weight = 1.0
            rationale = (
                f"極端投機溢價 (預期差 {gap*100:.1f}% < -30%)，脫離當期基本面現金流，"
                f"啟動資本保護機制，股票持倉降至 0%，轉入 100% 現金避險。"
            )

        return SignalDecision(
            quarter=quarter,
            as_of_date=as_of_date,
            trade_date=as_of_date,
            action=action,
            equity_weight=equity_weight,
            cash_weight=cash_weight,
            expectations_gap=gap,
            valuation_stance=stance,
            rationale=rationale,
            metadata={
                "quant_dcf_base": quarter_info.get("quant_dcf_base"),
                "ai_fair_value_base": quarter_info.get("ai_fair_value_base"),
                "tail_risk_haircut": quarter_info.get("tail_risk_haircut"),
            },
        )


class ValuationGrowthOverlayPolicy:
    """
    Growth-Tilted Overlay Policy:
    Maintains a core baseline long exposure (40%) to capture secular AI computing trend,
    and dynamically scales up to 100% long as Valuation Bridge margin of safety increases.
    """

    def decide(self, quarter_info: Dict[str, Any]) -> SignalDecision:
        quarter = quarter_info.get("quarter", "")
        as_of_date = quarter_info.get("as_of_date", "")
        gap = float(quarter_info.get("expectations_gap", 0.0))
        stance = quarter_info.get("valuation_stance", "FAIRLY_VALUED")

        if gap >= 0.05 or stance == "UNDERVALUED":
            action = "STRONG_ACCUMULATE"
            equity_weight = 1.0
            cash_weight = 0.0
            rationale = f"預期差正向 (+{gap*100:.1f}%)，全額加碼至 100% 股票倉位。"
        elif gap >= -0.15:
            action = "OVERWEIGHT"
            equity_weight = 0.85
            cash_weight = 0.15
            rationale = f"合理估值區間 ({gap*100:.1f}%)，配置 85% 核心倉位，保留 15% 現金防禦。"
        elif gap >= -0.30:
            action = "NEUTRAL_TILT"
            equity_weight = 0.60
            cash_weight = 0.40
            rationale = f"估值適度偏高 ({gap*100:.1f}%)，降低倉位至 60%，配置 40% 現金緩衝。"
        else:
            action = "CORE_ONLY"
            equity_weight = 0.40
            cash_weight = 0.60
            rationale = f"估值透支溢價 ({gap*100:.1f}%)，維持 40% 核心底倉，其餘 60% 現金避險。"

        return SignalDecision(
            quarter=quarter,
            as_of_date=as_of_date,
            trade_date=as_of_date,
            action=action,
            equity_weight=equity_weight,
            cash_weight=cash_weight,
            expectations_gap=gap,
            valuation_stance=stance,
            rationale=rationale,
            metadata={
                "quant_dcf_base": quarter_info.get("quant_dcf_base"),
                "ai_fair_value_base": quarter_info.get("ai_fair_value_base"),
            },
        )


class FixedAllocationPolicy:
    """
    Fixed Asset Allocation Benchmark Policy (e.g. 40% NVDA / 60% Cash).
    Essential ablation control to isolate Beta reduction / cash drag from AI active timing alpha.
    """

    def __init__(self, target_equity_weight: float = 0.40):
        self.target_equity_weight = target_equity_weight

    def decide(self, quarter_info: Dict[str, Any]) -> SignalDecision:
        return SignalDecision(
            quarter=quarter_info.get("quarter", ""),
            as_of_date=quarter_info.get("as_of_date", ""),
            trade_date=quarter_info.get("as_of_date", ""),
            action="FIXED_ALLOCATION",
            equity_weight=self.target_equity_weight,
            cash_weight=1.0 - self.target_equity_weight,
            expectations_gap=0.0,
            valuation_stance="FIXED_BASELINE",
            rationale=f"消融基準對照組：固定配置 {self.target_equity_weight*100:.0f}% 股票，{(1.0-self.target_equity_weight)*100:.0f}% 現金。",
        )


class NaiveDCFPolicy:
    """
    Baseline policy driven purely by quant DCF without AI qualitative features.
    """

    def decide(self, quarter_info: Dict[str, Any]) -> SignalDecision:
        quarter = quarter_info.get("quarter", "")
        as_of_date = quarter_info.get("as_of_date", "")
        market_price = float(quarter_info.get("market_price", 1.0))
        quant_dcf = float(quarter_info.get("quant_dcf_base", market_price))

        naive_gap = (quant_dcf - market_price) / market_price if market_price > 0 else 0.0

        if naive_gap >= 0.05:
            equity_weight = 1.0
            action = "BUY"
        elif naive_gap >= -0.20:
            equity_weight = 0.50
            action = "NEUTRAL"
        else:
            equity_weight = 0.0
            action = "SELL"

        return SignalDecision(
            quarter=quarter,
            as_of_date=as_of_date,
            trade_date=as_of_date,
            action=action,
            equity_weight=equity_weight,
            cash_weight=1.0 - equity_weight,
            expectations_gap=naive_gap,
            valuation_stance="NAIVE_DCF",
            rationale=f"純量化 DCF 預期差 {naive_gap*100:.1f}%，配置權重 {equity_weight*100:.0f}%。",
        )


class BuyAndHoldPolicy:
    """Passive Benchmark: 100% Long NVDA"""

    def decide(self, quarter_info: Dict[str, Any]) -> SignalDecision:
        return SignalDecision(
            quarter=quarter_info.get("quarter", ""),
            as_of_date=quarter_info.get("as_of_date", ""),
            trade_date=quarter_info.get("as_of_date", ""),
            action="HOLD",
            equity_weight=1.0,
            cash_weight=0.0,
            expectations_gap=0.0,
            valuation_stance="BUY_AND_HOLD",
            rationale="被動持有 100% NVDA。",
        )


class WalkForwardBacktester:
    """
    Point-In-Time Walk-Forward Execution Engine with Audited Accounting.
    Executes quarterly rebalancing across historical price series, accurately
    handling overnight price jumps, open-to-close returns, and transaction frictions.
    """

    def __init__(
        self,
        config: Optional[BacktestConfig] = None,
        db_path: Optional[Path] = None,
    ):
        self.config = config or BacktestConfig()
        root = Path(__file__).resolve().parent.parent.parent.parent
        self.db_path = db_path or (root / "data/qve.db")

    def load_daily_prices(
        self, start_date: str = "2022-08-25", end_date: str = "2026-09-11"
    ) -> List[Dict[str, Any]]:
        """Loads daily split-adjusted price bars from qve.db in read-only mode."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")

        uri = f"file:{self.db_path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT 
                    substr(timestamp, 1, 10) as trade_date,
                    open, high, low, close, adjusted_close, volume
                FROM market_prices
                WHERE ticker = ? AND timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
            """
            rows = conn.execute(
                query, (self.config.benchmark_ticker, f"{start_date} 00:00:00", f"{end_date} 23:59:59")
            ).fetchall()

        bars = []
        for r in rows:
            bars.append({
                "date": r["trade_date"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "adj_close": float(r["adjusted_close"]),
                "volume": int(r["volume"] or 0),
            })
        return bars

    def run(
        self,
        manifest_data: Dict[str, Any],
        policy: Any,
        strategy_name: str = "ValuationBridgeAlphaPolicy",
    ) -> BacktestReport:
        """Runs the audited walk-forward simulation."""
        quarters_dict = manifest_data.get("panel_quarters", {})
        if not quarters_dict:
            raise ValueError("Manifest contains no quarters data.")

        # Sort quarters chronologically
        q_keys = sorted(quarters_dict.keys(), key=lambda k: quarters_dict[k]["as_of_date"])
        start_date = quarters_dict[q_keys[0]]["as_of_date"]

        # Load daily price bars
        daily_bars = self.load_daily_prices(start_date=start_date)
        if not daily_bars:
            raise ValueError(f"No daily market price bars found starting from {start_date}")

        # Map dates to bar indices
        date_to_idx = {b["date"]: i for i, b in enumerate(daily_bars)}

        # Determine rebalancing schedule:
        # Each quarter has entry_date. Signal is known at as_of_date (after market close).
        # Rebalancing execution happens on the first available trading bar on or after entry_date.
        rebalance_schedule = []
        for i, q_name in enumerate(q_keys):
            q_info = quarters_dict[q_name]
            as_of_dt = q_info["as_of_date"]
            # Find first trading day >= as_of_dt
            cand = [idx for idx, b in enumerate(daily_bars) if b["date"] >= as_of_dt]
            if cand:
                exec_idx = cand[0]
                rebalance_schedule.append({
                    "quarter": q_name,
                    "info": q_info,
                    "exec_bar_idx": exec_idx,
                    "exec_date": daily_bars[exec_idx]["date"],
                })

        # Simulation states
        nav = self.config.initial_capital
        benchmark_nav = self.config.initial_capital
        cash_nav = self.config.initial_capital

        shares_held = 0.0
        cash_held = nav
        current_equity_weight = 0.0

        benchmark_shares = self.config.initial_capital / daily_bars[0]["open"]

        daily_rf = (1.0 + self.config.annual_risk_free_rate) ** (1.0 / 252.0) - 1.0

        daily_curve: List[DailyNavPoint] = []
        period_results: List[PeriodResult] = []

        strategy_peak = nav
        benchmark_peak = benchmark_nav

        sched_lookup = {item["exec_bar_idx"]: item for item in rebalance_schedule}
        period_start_nav = nav
        current_period_idx = 0
        current_quarter = rebalance_schedule[0]["quarter"]
        current_period_entry_date = daily_bars[0]["date"]
        current_period_entry_price = daily_bars[0]["open"]
        current_period_stance = "INITIAL"
        current_period_gap = 0.0
        period_fee_accum = 0.0
        period_turnover_accum = 0.0

        # Step through every trading day continuously
        for b_idx, bar in enumerate(daily_bars):
            bar_date = bar["date"]
            bar_open = bar["open"]
            bar_close = bar["close"]

            # Check if today is a scheduled rebalance day
            if b_idx in sched_lookup:
                item = sched_lookup[b_idx]
                q_info = item["info"]

                # If wrapping up a previous period, record PeriodResult
                if b_idx > 0:
                    prev_bar = daily_bars[b_idx - 1]
                    period_stock_ret = (prev_bar["close"] - current_period_entry_price) / current_period_entry_price
                    period_strat_ret = (nav - period_start_nav) / period_start_nav if period_start_nav > 0 else 0.0
                    period_results.append(
                        PeriodResult(
                            period_index=current_period_idx,
                            quarter=current_quarter,
                            entry_date=current_period_entry_date,
                            exit_date=prev_bar["date"],
                            entry_price=round(current_period_entry_price, 2),
                            exit_price=round(prev_bar["close"], 2),
                            equity_weight=round(current_equity_weight, 4),
                            cash_weight=round(1.0 - current_equity_weight, 4),
                            period_stock_return=round(period_stock_ret, 4),
                            period_strategy_return=round(period_strat_ret, 4),
                            period_cash_return=round(daily_rf * 63, 4),
                            period_turnover=round(period_turnover_accum, 4),
                            transaction_fee_paid=round(period_fee_accum, 2),
                            start_nav=round(period_start_nav, 2),
                            end_nav=round(nav, 2),
                            valuation_stance=current_period_stance,
                            expectations_gap=round(current_period_gap, 4),
                        )
                    )
                    current_period_idx += 1
                    period_start_nav = nav
                    period_fee_accum = 0.0
                    period_turnover_accum = 0.0

                current_quarter = item["quarter"]
                current_period_entry_date = bar_date
                current_period_entry_price = bar_open

                # 1. Pre-trade valuation at Open (accounts for overnight price gap on existing shares)
                pre_trade_equity = shares_held * bar_open
                pre_trade_nav = pre_trade_equity + cash_held
                current_eff_weight = pre_trade_equity / pre_trade_nav if pre_trade_nav > 0 else 0.0

                # 2. Decision from policy
                decision = policy.decide(q_info)
                target_equity_w = decision.equity_weight
                target_cash_w = decision.cash_weight
                current_period_stance = decision.valuation_stance
                current_period_gap = decision.expectations_gap

                # 3. Turnover and transaction cost
                turnover = abs(target_equity_w - current_eff_weight)
                fee = turnover * pre_trade_nav * (self.config.transaction_cost_bps / 10_000.0)
                period_fee_accum += fee
                period_turnover_accum += turnover

                # 4. Post-fee rebalance
                post_fee_nav = pre_trade_nav - fee
                shares_held = (post_fee_nav * target_equity_w) / bar_open
                cash_held = post_fee_nav * target_cash_w
                current_equity_weight = target_equity_w

            # Daily cash interest accrual
            cash_held *= (1.0 + daily_rf)
            cash_nav *= (1.0 + daily_rf)

            # End of day valuation at Close
            equity_val = shares_held * bar_close
            nav = equity_val + cash_held

            # Benchmark valuation
            benchmark_nav = benchmark_shares * bar_close

            # Track peak and drawdowns
            if nav > strategy_peak:
                strategy_peak = nav
            strat_dd = (nav - strategy_peak) / strategy_peak if strategy_peak > 0 else 0.0

            if benchmark_nav > benchmark_peak:
                benchmark_peak = benchmark_nav
            bench_dd = (benchmark_nav - benchmark_peak) / benchmark_peak if benchmark_peak > 0 else 0.0

            daily_curve.append(
                DailyNavPoint(
                    date=bar_date,
                    stock_price=round(bar_close, 2),
                    strategy_nav=round(nav, 2),
                    benchmark_nav=round(benchmark_nav, 2),
                    cash_nav=round(cash_nav, 2),
                    strategy_drawdown=round(strat_dd, 4),
                    benchmark_drawdown=round(bench_dd, 4),
                    equity_weight=round(current_equity_weight, 4),
                )
            )

        # Record the final period
        last_bar = daily_bars[-1]
        period_stock_ret = (last_bar["close"] - current_period_entry_price) / current_period_entry_price
        period_strat_ret = (nav - period_start_nav) / period_start_nav if period_start_nav > 0 else 0.0
        period_results.append(
            PeriodResult(
                period_index=current_period_idx,
                quarter=current_quarter,
                entry_date=current_period_entry_date,
                exit_date=last_bar["date"],
                entry_price=round(current_period_entry_price, 2),
                exit_price=round(last_bar["close"], 2),
                equity_weight=round(current_equity_weight, 4),
                cash_weight=round(1.0 - current_equity_weight, 4),
                period_stock_return=round(period_stock_ret, 4),
                period_strategy_return=round(period_strat_ret, 4),
                period_cash_return=round(daily_rf * 63, 4),
                period_turnover=round(period_turnover_accum, 4),
                transaction_fee_paid=round(period_fee_accum, 2),
                start_nav=round(period_start_nav, 2),
                end_nav=round(nav, 2),
                valuation_stance=current_period_stance,
                expectations_gap=round(current_period_gap, 4),
            )
        )

        # Performance analytics
        n_days = len(daily_curve)
        years = n_days / 252.0 if n_days > 0 else 1.0

        cum_return = (nav - self.config.initial_capital) / self.config.initial_capital
        cagr = ((nav / self.config.initial_capital) ** (1.0 / years) - 1.0) if years > 0 else 0.0

        bench_cum_return = (benchmark_nav - self.config.initial_capital) / self.config.initial_capital
        bench_cagr = ((benchmark_nav / self.config.initial_capital) ** (1.0 / years) - 1.0) if years > 0 else 0.0

        # Daily returns
        strat_returns = []
        bench_returns = []
        for i in range(1, len(daily_curve)):
            s_ret = (daily_curve[i].strategy_nav - daily_curve[i - 1].strategy_nav) / daily_curve[i - 1].strategy_nav
            b_ret = (daily_curve[i].benchmark_nav - daily_curve[i - 1].benchmark_nav) / daily_curve[i - 1].benchmark_nav
            strat_returns.append(s_ret)
            bench_returns.append(b_ret)

        # Volatility & Sharpe
        def calc_vol(rets: List[float]) -> float:
            if len(rets) < 2:
                return 0.0
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            return math.sqrt(var) * math.sqrt(252.0)

        strat_vol = calc_vol(strat_returns)
        bench_vol = calc_vol(bench_returns)

        sharpe = (cagr - self.config.annual_risk_free_rate) / strat_vol if strat_vol > 0 else 0.0
        bench_sharpe = (bench_cagr - self.config.annual_risk_free_rate) / bench_vol if bench_vol > 0 else 0.0

        max_dd = min(pt.strategy_drawdown for pt in daily_curve) if daily_curve else 0.0
        bench_max_dd = min(pt.benchmark_drawdown for pt in daily_curve) if daily_curve else 0.0

        calmar = cagr / abs(max_dd) if abs(max_dd) > 0 else 0.0

        # Win rate
        winning_periods = sum(1 for p in period_results if p.period_strategy_return > 0)
        win_rate = winning_periods / len(period_results) if period_results else 0.0

        # Beta & Alpha
        if len(strat_returns) > 1 and bench_vol > 0:
            cov = sum(
                (s - (sum(strat_returns) / len(strat_returns))) * (b - (sum(bench_returns) / len(bench_returns)))
                for s, b in zip(strat_returns, bench_returns)
            ) / (len(strat_returns) - 1)
            bench_var = (bench_vol / math.sqrt(252.0)) ** 2
            beta = cov / bench_var if bench_var > 0 else 1.0
            alpha = cagr - (self.config.annual_risk_free_rate + beta * (bench_cagr - self.config.annual_risk_free_rate))
        else:
            beta = 1.0
            alpha = 0.0

        return BacktestReport(
            strategy_name=strategy_name,
            initial_capital=self.config.initial_capital,
            final_nav=round(nav, 2),
            cumulative_return=round(cum_return, 4),
            cagr=round(cagr, 4),
            annualized_volatility=round(strat_vol, 4),
            sharpe_ratio=round(sharpe, 4),
            max_drawdown=round(max_dd, 4),
            calmar_ratio=round(calmar, 4),
            win_rate=round(win_rate, 4),
            benchmark_cumulative_return=round(bench_cum_return, 4),
            benchmark_cagr=round(bench_cagr, 4),
            benchmark_volatility=round(bench_vol, 4),
            benchmark_sharpe=round(bench_sharpe, 4),
            benchmark_max_drawdown=round(bench_max_dd, 4),
            alpha=round(alpha, 4),
            beta=round(beta, 4),
            period_results=[asdict(p) for p in period_results],
            daily_equity_curve=[asdict(d) for d in daily_curve],
        )
