"""Public regular-session quote, kept outside financial forecasts and AI context."""

import hashlib
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

import httpx

from valuation_engine.research.numbers import canonical

URL = "https://query1.finance.yahoo.com/v8/finance/chart/NVDA"
SOURCE = "https://finance.yahoo.com/quote/NVDA/"


def parse_quote(payload: dict, basis_date: str, observed_at: datetime) -> dict[str, Any]:
    result = payload["chart"]["result"]
    if payload["chart"].get("error") or not isinstance(result, list) or len(result) != 1:
        raise ValueError("invalid_quote_response")
    data = result[0]
    meta = data["meta"]
    if meta["symbol"] != "NVDA" or meta["currency"] != "USD":
        raise ValueError("quote_identity_mismatch")
    raw_price, timestamp = meta["regularMarketPrice"], meta["regularMarketTime"]
    if isinstance(raw_price, bool) or type(timestamp) is not int:
        raise ValueError("invalid_quote_number")
    price = Decimal(str(raw_price))
    quoted_at = datetime.fromtimestamp(timestamp, UTC)
    if not price.is_finite() or price <= 0 or quoted_at > observed_at:
        raise ValueError("invalid_quote_time_or_price")
    basis = date.fromisoformat(basis_date)
    if quoted_at.date() < basis:
        raise ValueError("quote_precedes_valuation_basis")
    split_factor = Decimal(1)
    events = []
    splits = data.get("events", {}).get("splits", {})
    if not isinstance(splits, dict):
        raise ValueError("invalid_split_events")
    for event in splits.values():
        at = datetime.fromtimestamp(event["date"], UTC)
        numerator, denominator = (
            Decimal(str(event["numerator"])),
            Decimal(str(event["denominator"])),
        )
        if any(not n.is_finite() or n <= 0 for n in (numerator, denominator)):
            raise ValueError("invalid_split_ratio")
        if basis < at.date() <= quoted_at.date():
            split_factor *= numerator / denominator
            events.append(
                {"at": at.isoformat(), "numerator": numerator, "denominator": denominator}
            )
    stale = (observed_at - quoted_at).total_seconds() > 5 * 86400
    return canonical(
        {
            "status": "stale" if stale else "available",
            "ticker": "NVDA",
            "currency": "USD",
            "price": price,
            "quoted_at": quoted_at,
            "retrieved_at": observed_at,
            "session": "regular",
            "label": "最近常規交易成交價",
            "provider": "Yahoo Finance",
            "source_url": SOURCE,
            "valuation_basis_date": basis_date,
            "split_factor_since_valuation": split_factor,
            "split_events": events,
            "basis_verification": "provider_asserted_split_events_not_independently_verified",
            "limitation": "不含盤前、盤後或夜盤；非保證即時報價。拆股紀錄來自同一供應商，未獨立核證。",
        }
    )


def fetch_quote(basis_date: str) -> dict[str, Any]:
    observed = datetime.now(UTC)
    try:
        start = datetime.combine(date.fromisoformat(basis_date), time(), UTC)
        response = httpx.get(
            URL,
            params={
                "period1": int(start.timestamp()),
                "period2": int(observed.timestamp()),
                "interval": "1d",
                "events": "splits",
            },
            headers={"User-Agent": "StockOS local research/1.0"},
            timeout=12,
            follow_redirects=False,
        )
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise ValueError("oversized_quote_response")
        return {
            **parse_quote(response.json(), basis_date, observed),
            "response_sha256": hashlib.sha256(response.content).hexdigest(),
        }
    except (
        httpx.HTTPError,
        ValueError,
        KeyError,
        TypeError,
        ArithmeticError,
        OSError,
        AttributeError,
    ):
        return {
            "status": "unavailable",
            "price": None,
            "provider": "Yahoo Finance",
            "source_url": SOURCE,
            "retrieved_at": observed.isoformat(),
            "reason": "報價或拆股紀錄目前無法核對，研究結果仍可使用；請稍後重試。",
        }


def compare_price(valuation: dict, quote: dict) -> dict:
    if valuation["status"] != "available" or quote["status"] != "available":
        return {"status": "unavailable", "gap": None, "reason": "估值或新近報價未齊備"}
    factor = Decimal(quote["split_factor_since_valuation"])
    model = Decimal(valuation["base"]) / factor
    return canonical(
        {
            "status": "available",
            "model_on_quote_basis": model,
            "gap": model / Decimal(quote["price"]) - 1,
            "split_factor": factor,
            "classification": "model_price_comparison_not_expected_return",
        }
    )
