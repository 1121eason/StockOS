import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import MarketPrice
from valuation_engine.db.store import company, digest
from valuation_engine.ingestion.http import SourceClient
from valuation_engine.time import aware, now, sessions


class PriceBar(BaseModel):
    timestamp: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal | None
    volume: int
    currency: str
    provider: str
    retrieved_at: datetime
    price_type: str

    @field_validator("timestamp", "available_at", "retrieved_at")
    @classmethod
    def timestamps(cls, value: datetime) -> datetime:
        return aware(value)


class MarketDataProvider(Protocol):
    def fetch(self, ticker: str, start: date, end: date) -> list[PriceBar]: ...


class YahooChartProvider:
    """Bootstrap only: current-vintage split-adjusted OHLC, NOT historical raw prices."""

    def __init__(self, client: SourceClient | None = None):
        self.client = client or SourceClient("QVE/0.1 market-research")

    def fetch(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        if ticker != "NVDA":
            raise ValueError("Milestone 1 supports NVDA only")
        p1 = int(datetime.combine(start, datetime.min.time(), UTC).timestamp())
        p2 = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC).timestamp())
        raw = self.client.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval=1d&events=div%2Csplits"
        )
        chart = json.loads(raw)["chart"]
        if chart.get("error"):
            raise ValueError(str(chart["error"]))
        result = chart["result"][0]
        quote = result["indicators"]["quote"][0]
        adjusted = result["indicators"].get("adjclose", [{}])[0].get("adjclose", [])
        schedule = sessions(str(start), str(end))
        retrieved = now()
        bars = []
        for i, unix in enumerate(result.get("timestamp", [])):
            day = datetime.fromtimestamp(unix, UTC).date()
            matches = schedule.loc[schedule.index.date == day]
            if matches.empty or any(
                quote[x][i] is None for x in ("open", "high", "low", "close", "volume")
            ):
                continue
            close_time = matches.iloc[0]["market_close"].to_pydatetime()
            if close_time > retrieved:
                continue  # never save an unfinished daily bar as complete
            bars.append(
                PriceBar(
                    timestamp=matches.iloc[0]["market_open"].to_pydatetime(),
                    available_at=close_time,
                    open=Decimal(str(quote["open"][i])),
                    high=Decimal(str(quote["high"][i])),
                    low=Decimal(str(quote["low"][i])),
                    close=Decimal(str(quote["close"][i])),
                    adjusted_close=Decimal(str(adjusted[i]))
                    if i < len(adjusted) and adjusted[i] is not None
                    else None,
                    volume=quote["volume"][i],
                    currency=result["meta"].get("currency", "USD"),
                    provider="Yahoo Chart",
                    retrieved_at=retrieved,
                    price_type="daily_split_adjusted_current_vintage",
                )
            )
        return bars


def ingest_prices(
    db: Session, provider: MarketDataProvider, start: date, end: date
) -> dict[str, int]:
    co = company(db)
    counts = {"created": 0, "skipped": 0}
    for bar in provider.fetch(co.ticker, start, end):
        content_hash = digest(bar.model_dump(mode="json", exclude={"retrieved_at"}))
        if db.scalar(
            select(MarketPrice.id).where(
                MarketPrice.company_id == co.id,
                MarketPrice.timestamp == bar.timestamp,
                MarketPrice.provider == bar.provider,
                MarketPrice.price_type == bar.price_type,
                MarketPrice.content_hash == content_hash,
            )
        ):
            counts["skipped"] += 1
            continue
        db.add(
            MarketPrice(
                company_id=co.id, ticker=co.ticker, content_hash=content_hash, **bar.model_dump()
            )
        )
        counts["created"] += 1
    return counts
