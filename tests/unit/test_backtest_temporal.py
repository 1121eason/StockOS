"""Synthetic calendar and availability checks, without historical data or tuning."""

from dataclasses import asdict
from datetime import datetime
from typing import Any

import pytest

from valuation_engine.backtest.walk_forward import (
    TIMING_VERSION,
    BacktestConfig,
    BuyAndHoldPolicy,
    WalkForwardBacktester,
)


def _bar(day: str, opening: float = 100.0, closing: float = 100.0) -> dict[str, Any]:
    return {"date": day, "open": opening, "close": closing}


def _run(monkeypatch, signals, bars):
    backtester = WalkForwardBacktester(
        config=BacktestConfig(annual_risk_free_rate=0.0, transaction_cost_bps=0.0)
    )
    monkeypatch.setattr(backtester, "load_daily_prices", lambda **kwargs: bars)
    return backtester.run({"panel_quarters": signals}, BuyAndHoldPolicy())


@pytest.mark.parametrize(
    ("as_of_date", "expected_date", "expected_offset"),
    [
        ("2024-01-03", "2024-01-04", "-05:00"),
        ("2024-01-05", "2024-01-08", "-05:00"),  # Friday
        ("2024-01-06", "2024-01-08", "-05:00"),  # Weekend
        ("2024-01-12", "2024-01-16", "-05:00"),  # MLK holiday
        ("2024-07-03", "2024-07-05", "-04:00"),  # Early close + holiday
        ("2024-07-04", "2024-07-05", "-04:00"),  # Holiday
        ("2024-11-29", "2024-12-02", "-05:00"),  # Thanksgiving early close
        ("2024-03-08", "2024-03-11", "-04:00"),  # Spring DST weekend
        ("2024-11-01", "2024-11-04", "-05:00"),  # Fall DST weekend
    ],
)
def test_date_only_waits_until_entire_local_date_elapses(
    monkeypatch, as_of_date, expected_date, expected_offset
):
    report = _run(monkeypatch, {"Q1": {"as_of_date": as_of_date}}, [_bar(expected_date)])
    timing = report.execution_schedule[0]
    assert report.period_results[0]["entry_date"] == expected_date
    assert timing["execution_at"] == f"{expected_date}T09:30:00{expected_offset}"
    assert timing["availability_basis"] == "date_only_conservative_boundary"
    assert timing["signal_available_at"] is None  # Never invent a publication timestamp.
    assert timing["availability_verified"] is False
    boundary = datetime.fromisoformat(timing["scheduling_available_at"])
    assert str(boundary.date()) > as_of_date
    assert boundary.hour == boundary.minute == boundary.second == 0
    assert datetime.fromisoformat(timing["execution_at"]) >= boundary


@pytest.mark.parametrize(
    ("as_of_date", "availability", "expected_open"),
    [
        ("2024-01-03", "2024-01-03T09:00:00-05:00", "2024-01-03T09:30:00-05:00"),
        ("2024-01-03", "2024-01-03T14:00:00Z", "2024-01-03T09:30:00-05:00"),
        ("2024-01-03", "2024-01-03T22:00:00+09:00", "2024-01-03T09:30:00-05:00"),
        ("2024-01-03", "2024-01-03T09:30:00-05:00", "2024-01-03T09:30:00-05:00"),
        ("2024-01-03", "2024-01-03T09:30:00.000001-05:00", "2024-01-04T09:30:00-05:00"),
        ("2024-01-03", "2024-01-03T10:00:00-05:00", "2024-01-04T09:30:00-05:00"),
        ("2024-01-03", "2024-01-03T16:00:00-05:00", "2024-01-04T09:30:00-05:00"),
        ("2024-01-05", "2024-01-05T20:00:00-05:00", "2024-01-08T09:30:00-05:00"),
        ("2024-01-06", "2024-01-06T09:00:00-05:00", "2024-01-08T09:30:00-05:00"),
        ("2024-07-03", "2024-07-03T13:01:00-04:00", "2024-07-05T09:30:00-04:00"),
        ("2024-07-04", "2024-07-04T09:00:00-04:00", "2024-07-05T09:30:00-04:00"),
        ("2024-03-10", "2024-03-10T23:00:00-04:00", "2024-03-11T09:30:00-04:00"),
        ("2024-11-03", "2024-11-03T23:00:00-05:00", "2024-11-04T09:30:00-05:00"),
    ],
)
def test_explicit_availability_uses_first_open_at_or_after_assertion(
    monkeypatch, as_of_date, availability, expected_open
):
    report = _run(
        monkeypatch,
        {"Q1": {"as_of_date": as_of_date, "signal_available_at": availability}},
        [_bar(expected_open[:10])],
    )
    timing = report.execution_schedule[0]
    assert timing["execution_at"] == expected_open
    assert datetime.fromisoformat(expected_open) >= datetime.fromisoformat(availability)
    assert timing["signal_available_at"] == availability
    assert timing["availability_basis"] == "explicit_unverified_source_assertion"
    assert timing["availability_verified"] is False


def test_after_close_signal_cannot_capture_same_date_open_or_overnight_gap(monkeypatch):
    report = _run(
        monkeypatch,
        {"Q1": {"as_of_date": "2024-01-03", "signal_available_at": "2024-01-03T20:00:00-05:00"}},
        [_bar("2024-01-03", 1.0, 2.0), _bar("2024-01-04", 200.0, 220.0)],
    )
    assert report.period_results[0]["entry_price"] == 200.0
    assert report.final_nav == 110_000.0
    assert report.cumulative_return == report.benchmark_cumulative_return == 0.1
    assert [point["date"] for point in report.daily_equity_curve] == ["2024-01-04"]
    assert len(report.period_results) == 1


@pytest.mark.parametrize(
    "availability",
    [None, "", 123, "garbage", "2024-01-03", "2024-01-03T09:00:00", "2024-01-03T25:00:00Z"],
)
def test_invalid_explicit_availability_fails_instead_of_date_fallback(monkeypatch, availability):
    with pytest.raises(ValueError, match="timezone-aware ISO timestamp"):
        _run(
            monkeypatch,
            {"Q1": {"as_of_date": "2024-01-03", "signal_available_at": availability}},
            [_bar("2024-01-04")],
        )


@pytest.mark.parametrize("as_of_date", [None, "", "20240103", "2024-02-30", "2024-01-03T00:00:00Z"])
def test_malformed_as_of_date_fails_closed(monkeypatch, as_of_date):
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _run(monkeypatch, {"Q1": {"as_of_date": as_of_date}}, [_bar("2024-01-04")])


def test_explicit_availability_cannot_predate_as_of_in_exchange_timezone(monkeypatch):
    with pytest.raises(ValueError, match="precedes its NASDAQ-local as_of_date"):
        _run(
            monkeypatch,
            {"Q1": {"as_of_date": "2024-01-03", "signal_available_at": "2024-01-03T00:01:00Z"}},
            [_bar("2024-01-04")],
        )


@pytest.mark.parametrize("bars", [[_bar("2024-01-05")], [_bar("2024-01-03")]])
def test_missing_first_eligible_bar_never_shifts_or_drops_signal(monkeypatch, bars):
    with pytest.raises(ValueError, match="Missing first eligible NASDAQ session bar 2024-01-04"):
        _run(monkeypatch, {"Q1": {"as_of_date": "2024-01-03"}}, bars)


def test_missing_final_signal_bar_fails_entire_run(monkeypatch):
    with pytest.raises(
        ValueError, match="Missing first eligible NASDAQ session bar 2024-01-05 for Q2"
    ):
        _run(
            monkeypatch,
            {"Q1": {"as_of_date": "2024-01-02"}, "Q2": {"as_of_date": "2024-01-04"}},
            [_bar("2024-01-03"), _bar("2024-01-04"), _bar("2024-01-08")],
        )


def test_colliding_weekend_signals_cannot_silently_overwrite(monkeypatch):
    with pytest.raises(ValueError, match="collide"):
        _run(
            monkeypatch,
            {"Q1": {"as_of_date": "2024-01-05"}, "Q2": {"as_of_date": "2024-01-06"}},
            [_bar("2024-01-08")],
        )


def test_availability_order_conflicting_with_as_of_order_fails(monkeypatch):
    with pytest.raises(ValueError, match="Signal availability order"):
        _run(
            monkeypatch,
            {
                "Q1": {
                    "as_of_date": "2024-01-02",
                    "signal_available_at": "2024-01-05T09:00:00-05:00",
                },
                "Q2": {
                    "as_of_date": "2024-01-03",
                    "signal_available_at": "2024-01-04T09:00:00-05:00",
                },
            },
            [_bar("2024-01-04"), _bar("2024-01-05")],
        )


def test_manifest_insertion_order_does_not_change_chronology(monkeypatch):
    report = _run(
        monkeypatch,
        {"Q2": {"as_of_date": "2024-01-03"}, "Q1": {"as_of_date": "2024-01-02"}},
        [_bar("2024-01-03"), _bar("2024-01-04")],
    )
    assert [period["quarter"] for period in report.period_results] == ["Q1", "Q2"]
    assert [period["entry_date"] for period in report.period_results] == [
        "2024-01-03",
        "2024-01-04",
    ]


@pytest.mark.parametrize(
    ("bars", "message"),
    [
        ([_bar("2024-01-04"), _bar("2024-01-04")], "unique, strictly increasing"),
        ([_bar("2024-01-05"), _bar("2024-01-04")], "unique, strictly increasing"),
        ([_bar("2024-01-04"), _bar("2024-01-06")], "not a NASDAQ regular session"),
        ([_bar("2024-01-01"), _bar("2024-01-04")], "not a NASDAQ regular session"),
        ([_bar("20240104")], "YYYY-MM-DD"),
        ([_bar("2024-01-04", 0.0)], "finite positive price"),
        ([_bar("2024-01-04", float("nan"))], "finite positive price"),
        ([_bar("2024-01-04", closing=float("inf"))], "finite positive price"),
    ],
)
def test_ambiguous_or_invalid_bars_fail_closed(monkeypatch, bars, message):
    with pytest.raises(ValueError, match=message):
        _run(monkeypatch, {"Q1": {"as_of_date": "2024-01-03"}}, bars)


def test_no_prices_fails_closed(monkeypatch):
    with pytest.raises(ValueError, match="No daily market price bars"):
        _run(monkeypatch, {"Q1": {"as_of_date": "2024-01-03"}}, [])


def test_report_is_always_an_unverified_reconstruction_diagnostic(monkeypatch):
    report = _run(
        monkeypatch,
        {
            "Q1": {
                "as_of_date": "2024-01-03",
                "signal_available_at": "2024-01-03T09:00:00-05:00",
                "historical_oos": True,
                "classification": "verified_point_in_time",
                "source_vintages_verified": True,
            }
        },
        [_bar("2024-01-03")],
    )
    exported = asdict(report)
    assert exported["classification"] == "reconstruction_diagnostic"
    assert exported["historical_oos"] is False
    assert exported["timing_version"] == TIMING_VERSION
    for field in ("source_vintages_verified", "model_vintages_verified", "price_vintages_verified"):
        assert exported[field] is False
    assert any("not comparable" in warning for warning in exported["limitations"])
    assert any("unverified source assertions" in warning for warning in exported["limitations"])
    assert any(
        "not an actual publication timestamp" in warning for warning in exported["limitations"]
    )
