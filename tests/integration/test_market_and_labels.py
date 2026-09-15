from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from valuation_engine.backtest.labels import build_outcome
from valuation_engine.db.schema import LabelBase, MarketPrice
from valuation_engine.db.session import engine
from valuation_engine.db.store import company
from valuation_engine.ingestion.http import SourceClient
from valuation_engine.ingestion.market import YahooChartProvider, ingest_prices
from valuation_engine.normalization.quarterly import PointInTimeRepository
from valuation_engine.valuation.ratios import value_at


def test_market_provider_contract_and_idempotency(db):
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"currency": "USD"},
                    "timestamp": [1685021400],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100],
                                "high": [110],
                                "low": [90],
                                "close": [105],
                                "volume": [1000],
                            }
                        ],
                        "adjclose": [{"adjclose": [104]}],
                    },
                }
            ],
        }
    }
    client = SourceClient(
        client=httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
        )
    )
    provider = YahooChartProvider(client)
    assert ingest_prices(db, provider, date(2023, 5, 25), date(2023, 5, 25)) == {
        "created": 1,
        "skipped": 0,
    }
    db.flush()
    assert ingest_prices(db, provider, date(2023, 5, 25), date(2023, 5, 25)) == {
        "created": 0,
        "skipped": 1,
    }
    bar = db.scalar(select(MarketPrice))
    assert bar.price_type == "daily_split_adjusted_current_vintage"
    assert bar.adjusted_close == D(104) and bar.close == D(105)
    assert bar.available_at == datetime(2023, 5, 25, 20, tzinfo=UTC)


def test_adjusted_price_not_used_for_historical_valuation(db, add):
    add("revenue", 100)
    co = company(db)
    db.add(
        MarketPrice(
            company_id=co.id,
            ticker="NVDA",
            timestamp=datetime(2023, 5, 25, 13, 30, tzinfo=UTC),
            available_at=datetime(2023, 5, 25, 20, tzinfo=UTC),
            price_type="daily_split_adjusted_current_vintage",
            open=D(100),
            high=D(100),
            low=D(100),
            close=D(100),
            adjusted_close=D(100),
            volume=1,
            currency="USD",
            provider="test",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            content_hash="synthetic",
        )
    )
    at = datetime(2023, 6, 1, tzinfo=UTC)
    repo = PointInTimeRepository(db, co.id)
    row = value_at(db, repo, repo.quarter(2024, 1, at), at)
    assert row.market_cap is None and row.fy1_pe is None
    assert row.metadata_json["price_id"] is None


def test_labels_entry_and_unmatured_horizons(db, tmp_path):
    co = company(db)
    for n, (opening, closing) in enumerate([(100, 105), (110, 100)]):
        day = datetime(2023, 5, 25 + n, 13, 30, tzinfo=UTC)
        db.add(
            MarketPrice(
                company_id=co.id,
                ticker="NVDA",
                timestamp=day,
                available_at=day + timedelta(hours=6, minutes=30),
                price_type="daily_split_adjusted_current_vintage",
                open=D(opening),
                high=D(120),
                low=D(90),
                close=D(closing),
                adjusted_close=None,
                volume=1,
                currency="USD",
                provider="test",
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                content_hash=str(n),
            )
        )
    label_engine = engine(f"sqlite:///{tmp_path}/labels.db")
    LabelBase.metadata.create_all(label_engine)
    with Session(label_engine) as labels:
        row = build_outcome(
            db,
            labels,
            co.id,
            datetime(2023, 5, 24, 20, 20, tzinfo=UTC),
            datetime(2023, 5, 27, tzinfo=UTC),
        )
        assert row.price_3m is None and row.return_3m is None
        assert row.max_drawdown_12m is None
        assert row.alignment_json["first_tradable_price"] == "100.00000000"
        assert row.alignment_json["1d"] == "105.00000000"
    with pytest.raises(DBAPIError):
        db.execute(text("select * from future_outcomes"))
