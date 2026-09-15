from decimal import Decimal as D

import pytest

from valuation_engine.research.dcf import DCFModel, ReverseDCFModel, enterprise_pv
from valuation_engine.research.numbers import MarketEquityShares


def value(wacc=D(".10"), g=D(".025"), fcf=D(100), cash=D(20), debt=D(10), shares=D(10)):
    return DCFModel().value([fcf] * 5, cash, debt, MarketEquityShares(shares), wacc, g)["per_share"]


def test_dcf_monotonic_cash_debt_discount_and_growth():
    baseline = value()
    assert value(wacc=D(".12")) < baseline
    assert value(g=D(".03")) > baseline
    assert value(fcf=D(110)) > baseline
    assert value(debt=D(20)) < baseline
    assert value(cash=D(30)) > baseline


@pytest.mark.parametrize("factor", [D(4), D(10), D(40)])
def test_dcf_split_denominator_transformation(factor):
    assert abs(value() / factor - value(shares=D(10) * factor)) < D("1e-20")


def test_reverse_dcf_price_wacc_and_recovery():
    start, g, wacc, t = D(100), D(".20"), D(".10"), D(".025")
    price = enterprise_pv([start * (1 + g) ** i for i in range(1, 6)], wacc, t)
    r = ReverseDCFModel().solve(price, start, wacc, t)
    assert r["status"] == "converged" and abs(r["implied_growth"] - g) < D("1e-8")
    assert r["relative_residual"] <= D("1e-10")
    assert (
        ReverseDCFModel().solve(price * D("1.1"), start, wacc, t)["implied_growth"]
        > r["implied_growth"]
    )
    assert (
        ReverseDCFModel().solve(price, start, D(".12"), t)["implied_growth"] > r["implied_growth"]
    )


@pytest.mark.parametrize(
    "ev,start,wacc,g",
    [
        (D(-1), D(100), D(".1"), D(".02")),
        (D(1000), D(0), D(".1"), D(".02")),
        (D(1000), D(100), D(".02"), D(".02")),
        (D("1e20"), D(1), D(".1"), D(".02")),
        (D("NaN"), D(1), D(".1"), D(".02")),
    ],
)
def test_reverse_invalid_and_unbracketed_fail_explicitly(ev, start, wacc, g):
    r = ReverseDCFModel().solve(ev, start, wacc, g)
    assert r["status"] == "unavailable" and "implied_growth" not in r


def test_dcf_missing_balances_not_zero():
    r = DCFModel().value([D(100)] * 5, D(20), None, MarketEquityShares(D(10)), D(".1"), D(".02"))
    assert r["status"] == "unavailable"


def test_reverse_convergence_failure_is_explicit(monkeypatch):
    from valuation_engine.research.numbers import POLICY

    monkeypatch.setitem(POLICY, "reverse_max_iterations", 1)
    result = ReverseDCFModel().solve(D(2000), D(100), D(".10"), D(".025"))
    assert result["status"] == "unavailable" and result["reason"] == "maximum_iterations"
