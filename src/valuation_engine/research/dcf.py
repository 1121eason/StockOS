"""Enterprise-compatible NOPAT cash-conversion proxy, not unadjusted CFO-capex FCFF."""

from dataclasses import dataclass
from typing import Any

from valuation_engine.research.forecast import fcff_proxy
from valuation_engine.research.numbers import POLICY, D, MarketEquityShares, bound, p, total


def enterprise_pv(cashflows, wacc, terminal_growth):
    if not cashflows or any(v is None or not v.is_finite() for v in cashflows):
        raise ValueError("Finite explicit cash flows required")
    if (
        not wacc.is_finite()
        or not terminal_growth.is_finite()
        or wacc <= terminal_growth
        or wacc <= 0
        or terminal_growth <= -1
    ):
        raise ValueError("Require positive WACC > terminal growth > -100%")
    if cashflows[-1] <= 0:
        raise ValueError("Positive terminal-period cash flow required")
    explicit = sum((v / (1 + wacc) ** year for year, v in enumerate(cashflows, 1)), D(0))
    terminal = (
        cashflows[-1]
        * (1 + terminal_growth)
        / (wacc - terminal_growth)
        / (1 + wacc) ** len(cashflows)
    )
    return explicit + terminal


@dataclass(frozen=True)
class DCFModel:
    version: str = "DCFPolicyV1"

    def value(
        self, cashflows, cash, debt, shares: MarketEquityShares | None, wacc, terminal_growth
    ):
        if (
            any(x is None or not x.is_finite() for x in (cash, debt, shares))
            or cash < 0
            or debt < 0
            or shares is None
            or shares <= 0
        ):
            return {"status": "unavailable", "reason": "missing_or_invalid_cash_debt_or_pit_shares"}
        try:
            ev = enterprise_pv(cashflows, wacc, terminal_growth)
        except ValueError as exc:
            return {"status": "unavailable", "reason": str(exc)}
        equity = ev + cash - debt
        return dict(
            status="available",
            enterprise_value=ev,
            equity_value=equity,
            per_share=equity / shares,
            wacc=wacc,
            terminal_growth=terminal_growth,
            version=self.version,
            negative_equity_warning=equity < 0,
        )


@dataclass(frozen=True)
class ReverseDCFModel:
    version: str = "ReverseDCFPolicyV1"

    def solve(self, current_ev, starting_fcf, wacc, terminal_growth):
        if (
            current_ev is None
            or starting_fcf is None
            or not current_ev.is_finite()
            or not starting_fcf.is_finite()
            or current_ev <= 0
            or starting_fcf <= 0
        ):
            return {
                "status": "unavailable",
                "reason": "positive_finite_ev_and_starting_fcff_required",
                "version": self.version,
            }
        lo, hi = p("reverse_growth_min"), p("reverse_growth_max")
        years = POLICY["dcf_years"]

        def residual(growth):
            return (
                enterprise_pv(
                    [starting_fcf * (1 + growth) ** year for year in range(1, years + 1)],
                    wacc,
                    terminal_growth,
                )
                - current_ev
            )

        try:
            left, right = residual(lo), residual(hi)
        except ValueError as exc:
            return {"status": "unavailable", "reason": str(exc), "version": self.version}
        if left > 0 or right < 0:
            return dict(
                status="unavailable",
                reason="root_not_bracketed",
                growth_bounds=[lo, hi],
                endpoint_residuals=[left, right],
                version=self.version,
            )
        for iteration in range(1, POLICY["reverse_max_iterations"] + 1):
            mid = (lo + hi) / 2
            error = residual(mid)
            if abs(error) / current_ev <= p("reverse_relative_tolerance"):
                return dict(
                    status="converged",
                    implied_growth=mid,
                    iterations=iteration,
                    residual=error,
                    relative_residual=abs(error) / current_ev,
                    starting_fcff=starting_fcf,
                    current_ev=current_ev,
                    wacc=wacc,
                    terminal_growth=terminal_growth,
                    version=self.version,
                )
            if error < 0:
                lo = mid
            else:
                hi = mid
        return dict(
            status="unavailable", reason="maximum_iterations", residual=error, version=self.version
        )


def explicit_fcff(periods):
    rows = [r for r in periods if r["period_type"] == "quarter"]
    warnings: list[dict[str, Any]] = []
    first = total([fcff_proxy(r) for r in rows[:4]]) if len(rows) >= 4 else None
    second = total([fcff_proxy(r) for r in rows[4:8]]) if len(rows) >= 8 else None
    if first is None or second is None or first <= 0 or second <= 0:
        return dict(
            status="unavailable",
            reason="two_positive_complete_forward_fcff_years_required",
            warnings=warnings,
        )
    growth = bound(
        second / first - 1,
        p("dcf_growth_min"),
        p("dcf_growth_max"),
        "year2_growth_for_extension",
        warnings,
    )
    flows = [first, second]
    for _year in range(3, POLICY["dcf_years"] + 1):
        growth = p("terminal_growth_base") + (growth - p("terminal_growth_base")) * p(
            "dcf_growth_decay"
        )
        flows.append(flows[-1] * (1 + growth))
    return dict(
        status="available",
        cashflows=flows,
        warnings=warnings,
        formula="FCFF proxy = EBIT*(1-tax) + (forecast OCF - forecast net income) - capex",
        limitations="Noncash, working-capital and nonoperating cash classification remain approximations; SBC is not expensed again. Unadjusted CFO-capex is never labeled FCFF.",
    )
