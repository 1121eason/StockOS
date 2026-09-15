from datetime import datetime
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import FutureOutcome, MarketPrice
from valuation_engine.db.store import digest
from valuation_engine.time import aware, calculate_next_tradable_timestamp, sessions


def build_outcome(
    prices_db: Session, labels_db: Session, company_id: int, release_at: datetime, as_of: datetime
) -> FutureOutcome | None:
    """Label-only consumer. Does not expose any path back to feature/forecast inputs."""
    as_of = aware(as_of)
    tradable = calculate_next_tradable_timestamp(release_at)
    existing = labels_db.scalar(
        select(FutureOutcome).where(
            FutureOutcome.company_id == company_id,
            FutureOutcome.anchor_timestamp == tradable,
            FutureOutcome.label_as_of == as_of,
        )
    )
    if existing:
        return existing
    raw = prices_db.scalars(
        select(MarketPrice)
        .where(MarketPrice.company_id == company_id, MarketPrice.available_at <= as_of)
        .order_by(MarketPrice.timestamp, MarketPrice.retrieved_at.desc())
    ).all()
    by_time: dict[datetime, MarketPrice] = {}
    for p in raw:
        by_time.setdefault(p.timestamp, p)
    bars = list(by_time.values())
    indices = [i for i, p in enumerate(bars) if p.timestamp >= tradable]
    if not indices:
        return None
    idx = indices[0]
    entry = bars[idx]
    if (entry.timestamp - tradable).total_seconds() > 1:
        raise ValueError("First tradable session missing; do not silently skip entry")
    if len({(p.provider, p.price_type) for p in bars}) != 1:
        raise ValueError("Labels require one consistent provider and price adjustment basis")
    prior_close = next((p for p in reversed(bars) if p.available_at <= aware(release_at)), None)
    # OHLC in one current split basis; dividend-adjusted close is not mixed with split-only open.
    align: dict[str, object] = {
        "pre_earnings_price": str(prior_close.close) if prior_close else None,
        "first_tradable_price": str(entry.open),
        "price_type": entry.price_type,
        "return_definition": "split-adjusted price return, excludes dividends",
        "source_price_ids": [p.id for p in bars],
        "model_version": "labels-1.0",
    }
    trading_dates = sessions(
        str(tradable.date()), str((pd.Timestamp(tradable) + pd.DateOffset(days=45)).date())
    )
    for n in (1, 5, 20):
        expected = trading_dates.iloc[n - 1]["market_open"].to_pydatetime()
        bar = by_time.get(expected)
        align[f"{n}d"] = str(bar.close) if bar else None
    fields: dict[str, Decimal | None] = {}
    for n in (3, 6, 12, 24):
        target = (pd.Timestamp(tradable) + pd.DateOffset(months=n)).to_pydatetime()
        expected = calculate_next_tradable_timestamp(target)
        match = by_time.get(expected)
        fields[f"price_{n}m"] = match.close if match else None
        fields[f"return_{n}m"] = match.close / entry.open - 1 if match else None
    end = (pd.Timestamp(tradable) + pd.DateOffset(months=12)).to_pydatetime()
    window = [p for p in bars[idx:] if p.timestamp <= end]
    complete = bool(fields["price_12m"])
    expected_window = sessions(str(tradable.date()), str(end.date()))["market_open"]
    complete = complete and all(t.to_pydatetime() in by_time for t in expected_window)
    peak = entry.open
    drawdown = Decimal(0)
    for bar in window:
        peak = max(peak, bar.close)
        drawdown = min(drawdown, bar.close / peak - 1)
    row = FutureOutcome(
        company_id=company_id,
        anchor_timestamp=tradable,
        label_as_of=as_of,
        **fields,
        max_drawdown_12m=drawdown if complete else None,
        max_upside_12m=max((p.close / entry.open - 1 for p in window), default=Decimal(0))
        if complete
        else None,
        alignment_json={**align, "input_hash": digest(align)},
    )
    labels_db.add(row)
    labels_db.flush()
    return row
