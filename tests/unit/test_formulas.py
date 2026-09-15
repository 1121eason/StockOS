from decimal import Decimal as D

import pytest

from valuation_engine.features.engine import divide, dso, fcf, growth
from valuation_engine.forecasts.baseline import forecast_revision
from valuation_engine.valuation.ratios import basic_ratios


@pytest.mark.parametrize(
    "a,b,expected",
    [(120, 100, ".2"), (80, 100, "-.2"), (100, 100, "0"), (0, 100, "-1"), (-10, 100, "-1.1")],
)
def test_growth(a, b, expected):
    assert growth(D(a), D(b)) == D(expected)


@pytest.mark.parametrize("a,b", [(None, D(10)), (D(10), None), (D(10), D(0)), (D(10), D(-2))])
def test_invalid_denominators(a, b):
    assert divide(a, b) is None
    assert growth(a, b) is None


def test_fcf_and_revision():
    assert fcf(D(24_077), D(2_677)) == D(21_400)
    assert forecast_revision(D(3), D(2)) == D(".5")
    with pytest.raises(ValueError):
        fcf(D(5), D(-1))


def test_dso_average_and_approximation():
    value, meta = dso(D(1000), D(300), D(200), 91)
    assert value == D("22.75")
    assert not meta["approximation"]
    value, meta = dso(D(1000), D(300), None, 91)
    assert value == D("27.3") and meta["approximation"]


def test_valuation_formulas():
    r = basic_ratios(
        price=D(20),
        shares=D(100),
        cash=D(200),
        debt=D(500),
        eps_ttm=D(2),
        fcf_ttm=D(100),
        ebit_ttm=D(230),
        da_ttm=D(20),
    )
    assert r["market_cap"] == D(2000)
    assert r["enterprise_value"] == D(2300)
    assert r["trailing_pe"] == D(10)
    assert r["ev_ebit"] == D(10)
    assert r["ev_ebitda"] == D("9.2")
    assert r["fcf_yield"] == D(".05")
