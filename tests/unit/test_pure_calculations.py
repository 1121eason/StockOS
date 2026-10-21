"""Calculation boundaries must work in a fresh interpreter without data adapters."""

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal as D
from pathlib import Path
from textwrap import dedent

import pytest

from valuation_engine.calendar_math import fiscal_start, period_name, period_tuple, prior_period
from valuation_engine.research.cashflows import fcff_proxy
from valuation_engine.research.forecast import aggregate, days, financial_row
from valuation_engine.research.numbers import EPSForecastShares, MarketEquityShares, canonical

SRC = Path(__file__).resolve().parents[2] / "src"


@pytest.mark.parametrize(
    "module,exercise",
    [
        (
            "valuation_engine.calendar_math",
            "assert module.fiscal_start(2022, 1) == date(2021, 2, 1)",
        ),
        (
            "valuation_engine.research.cashflows",
            "assert module.fcff_proxy(dict(free_cash_flow=D(100), net_income=D(90), "
            "operating_income=D(120), tax_rate=D('.2'))) == D(106)",
        ),
        (
            "valuation_engine.research.numbers",
            "assert module.canonical(D('1.2')) == '1.20000000'",
        ),
        (
            "valuation_engine.research.forecast",
            """
            from typing import get_type_hints
            assert get_type_hints(module.produce)['data'] is module.ForecastInputs
            assert get_type_hints(module.produce)['policy'] is module.ForecastPolicyV1
            assert 'FinancialInputs' in dir(module)
            assert 'FinancialInputs' not in vars(module)
            assert module.days(2021, 4) == D(98)
            data = SimpleNamespace(
                anchor=(2024, 4), current=None, history=[None] * 12,
                value=lambda quarter, metric: None, quarter=lambda fy, fq: None,
                guidance_accuracy=lambda: {key: [] for key in
                    ('revenue', 'gross_margin', 'operating_expenses')},
                guidance_for=lambda fy, fq: {}, warnings=[], provenance=lambda: {},
                basis_date=date(2024, 2, 20), at=datetime(2024, 2, 20, tzinfo=UTC),
            )
            result = module.produce(data, module.ForecastPolicyV1())
            assert len(result['periods']) == 11
            assert result['metadata']['anchor'] == 'FY2024-Q4'
            assert result['metadata']['starting_fcff'] is None
            """,
        ),
        (
            "valuation_engine.research.dcf",
            "assert module.enterprise_pv([D(100)] * 5, D('.1'), D('.025')) "
            "== D('1227.671151788356897297543428')",
        ),
    ],
)
def test_calculations_import_without_data_adapters(module, exercise, tmp_path):
    script = dedent(
        """
        import importlib
        import importlib.abc
        import sys
        from datetime import UTC, date, datetime
        from decimal import Decimal as D
        from types import SimpleNamespace

        blocked = {'sqlalchemy', 'alembic', 'bs4', 'httpx', 'pydantic_settings',
                   'pydantic', 'pandas', 'pandas_market_calendars'}
        attempts = []

        class BlockAdapters(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.')[0] in blocked:
                    attempts.append(fullname)
                    raise ImportError('Forbidden calculation dependency: ' + fullname)

        assert not blocked.intersection(sys.modules)
        sys.meta_path.insert(0, BlockAdapters())
        """
    )
    # -I -S excludes installed packages, startup hooks, and inherited PYTHONPATH.
    script += f"\nsys.path.insert(0, {str(SRC)!r})\nmodule = importlib.import_module({module!r})\n"
    script += dedent(exercise).strip() + "\n"
    script += "assert not attempts\nassert not blocked.intersection(sys.modules)\n"
    script += (
        "assert not any(name.startswith(('valuation_engine.db.', "
        "'valuation_engine.ingestion.', 'valuation_engine.normalization.')) "
        "or name == 'valuation_engine.research.inputs' for name in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "fy,fq,expected,length",
    [
        (2021, 4, "2020-10-26", 98),
        (2022, 1, "2021-02-01", 91),
        (2024, 4, "2023-10-30", 91),
        (2025, 1, "2024-01-29", 91),
        (2025, 2, "2024-04-29", 91),
        (2027, 4, "2026-10-26", 98),
        (2028, 1, "2027-02-01", 91),
    ],
)
def test_fiscal_calendar_preserves_leap_year_and_53_week_boundaries(fy, fq, expected, length):
    assert fiscal_start(fy, fq) == date.fromisoformat(expected)
    assert days(fy, fq) == D(length)


@pytest.mark.parametrize(
    "fy,fq,offset,expected",
    [
        (2024, 1, 1, (2023, 4)),
        (2024, 4, -1, (2025, 1)),
        (2024, 2, 0, (2024, 2)),
        (2024, 2, 9, (2022, 1)),
        (2024, 2, -9, (2026, 3)),
    ],
)
def test_period_rolls_and_labels(fy, fq, offset, expected):
    assert prior_period(fy, fq, offset) == expected
    assert period_tuple(period_name(*expected)) == expected
    assert prior_period(fy, fq) == prior_period(fy, fq, 1)


def test_period_helpers_retain_existing_permissive_behavior():
    assert period_tuple("2024-Q1") == (2024, 1)
    assert period_tuple("FY2024-Q0") == (2024, 0)
    assert period_name(2024, 5) == "FY2024-Q5"
    # Quarter 5 is a fixed 52-week offset, not the next fiscal year's start.
    assert fiscal_start(2021, 5) == date(2021, 1, 25)
    assert fiscal_start(2021, 5) != fiscal_start(2022, 1)
    with pytest.raises(ValueError):
        period_tuple("FY2024")


def cashflow_row(**changes):
    return dict(
        {
            "free_cash_flow": D(100),
            "net_income": D(90),
            "operating_income": D(120),
            "tax_rate": D(".2"),
        },
        **changes,
    )


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, D(106)),
        ({"tax_rate": D(0)}, D(130)),
        ({"tax_rate": D(1)}, D(10)),
        ({"tax_rate": D("-.01")}, None),
        ({"tax_rate": D("1.01")}, None),
        ({"operating_income": D(-120)}, D(-86)),
        ({"free_cash_flow": D(0)}, D(6)),
        ({"net_income": D(0)}, D(196)),
    ],
)
def test_fcff_proxy_regression(changes, expected):
    row = cashflow_row(**changes)
    before = row.copy()
    assert fcff_proxy(row) == expected
    assert row == before


@pytest.mark.parametrize("field", ["free_cash_flow", "net_income", "operating_income", "tax_rate"])
def test_fcff_proxy_missing_inputs_stay_unavailable(field):
    row = cashflow_row()
    row[field] = None
    assert fcff_proxy(row) is None
    del row[field]
    assert fcff_proxy(row) is None
    assert fcff_proxy(None) is None


def test_annual_share_weighting_retains_53_week_quarter_and_accounting_identity():
    rows = [
        financial_row(
            2021,
            fq,
            fq,
            D(100),
            D(".6"),
            D(20),
            D(".2"),
            D(".01"),
            EPSForecastShares(D(10 * fq)),
            D(".35"),
            D(".03"),
            D(".052"),
            [],
        )
        for fq in range(1, 5)
    ]
    annual = aggregate(rows, "FY1", 2021)
    expected_shares = D(10 * 91 + 20 * 91 + 30 * 91 + 40 * 98) / D(371)
    assert annual["diluted_weighted_shares"] == expected_shares
    assert annual["eps"] == annual["net_income"] / expected_shares
    assert annual["operating_cash_flow"] - annual["capex"] == annual["free_cash_flow"]
    assert fcff_proxy(annual) == D("136.800")
    assert annual["metadata_json"]["components"] == [
        {"period": f"FY2021-Q{fq}", "kind": "quarter"} for fq in range(1, 5)
    ]


def test_public_reexports_retain_helper_identity():
    from valuation_engine.ingestion import ir
    from valuation_engine.normalization import quarterly
    from valuation_engine.research import dcf, forecast, inputs

    assert ir.fiscal_start is fiscal_start
    assert quarterly.prior_period is prior_period
    assert inputs.period_name is period_name
    assert inputs.period_tuple is period_tuple
    assert forecast.fcff_proxy is fcff_proxy
    assert dcf.fcff_proxy is fcff_proxy


def test_concrete_financial_inputs_export_remains_compatible():
    from valuation_engine.research import forecast
    from valuation_engine.research.forecast import FinancialInputs as legacy_inputs
    from valuation_engine.research.inputs import FinancialInputs

    assert legacy_inputs is FinancialInputs
    assert forecast.FinancialInputs is FinancialInputs
    assert "FinancialInputs" in dir(forecast)
    with pytest.raises(AttributeError, match="unknown_input"):
        _ = forecast.unknown_input


def test_identity_serialization_and_share_types_are_unchanged():
    payload = {
        "at": datetime(2024, 2, 20, 20, tzinfo=UTC),
        "period": (2024, 4),
        "shares": [EPSForecastShares(D("2.5")), MarketEquityShares(D("3.25"))],
        "cashflow": fcff_proxy(cashflow_row()),
        "missing": None,
    }
    assert json.dumps(canonical(payload), sort_keys=True) == (
        '{"at": "2024-02-20T20:00:00+00:00", "cashflow": "106.00000000", '
        '"missing": null, "period": [2024, 4], "shares": ["2.50000000", "3.25000000"]}'
    )
