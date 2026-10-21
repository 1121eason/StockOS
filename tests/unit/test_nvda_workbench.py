"""Synthetic contract/fault tests, not NVIDIA financial acceptance evidence."""

import copy
import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from valuation_engine.research import market_quote, workbench
from valuation_engine.research.dcf import DCFModel
from valuation_engine.research.numbers import MarketEquityShares, canonical

NOW = datetime(2026, 10, 21, 2, tzinfo=UTC)


def quote_payload():
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "symbol": "NVDA",
                        "currency": "USD",
                        "regularMarketPrice": 200,
                        "regularMarketTime": int((NOW - timedelta(hours=6)).timestamp()),
                    }
                }
            ],
        }
    }


def test_regular_quote_binds_identity_time_and_current_share_basis():
    payload = quote_payload()
    payload["chart"]["result"][0]["events"] = {
        "splits": {
            "a": {
                "date": int(datetime(2026, 10, 1, tzinfo=UTC).timestamp()),
                "numerator": 10,
                "denominator": 1,
            }
        }
    }
    quote = market_quote.parse_quote(payload, "2026-08-27", NOW)
    assert quote["session"] == "regular"
    assert quote["split_factor_since_valuation"] == "10.00000000"
    result = market_quote.compare_price({"status": "available", "base": "2500"}, quote)
    assert result["model_on_quote_basis"] == "250.00000000"
    assert result["gap"] == "0.25000000"
    assert result["classification"] == "model_price_comparison_not_expected_return"


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "OTHER"),
        ("currency", "TWD"),
        ("regularMarketPrice", True),
        ("regularMarketPrice", "NaN"),
        ("regularMarketPrice", -1),
        ("regularMarketTime", True),
        ("regularMarketTime", int((NOW + timedelta(days=1)).timestamp())),
    ],
)
def test_invalid_quote_never_becomes_a_current_price(field, value):
    payload = quote_payload()
    payload["chart"]["result"][0]["meta"][field] = value
    with pytest.raises(ValueError):
        market_quote.parse_quote(payload, "2026-08-27", NOW)


def test_old_quote_retains_timestamp_but_cannot_produce_a_price_gap():
    payload = quote_payload()
    payload["chart"]["result"][0]["meta"]["regularMarketTime"] = int(
        (NOW - timedelta(days=8)).timestamp()
    )
    quote = market_quote.parse_quote(payload, "2026-08-27", NOW)
    assert quote["status"] == "stale"
    assert market_quote.compare_price({"status": "available", "base": "250"}, quote)["gap"] is None


def test_unavailable_quote_does_not_replace_model_value(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ValueError("bad public response")

    monkeypatch.setattr(market_quote.httpx, "get", unavailable)
    quote = market_quote.fetch_quote("2026-08-27")
    assert quote["status"] == "unavailable"
    assert quote["price"] is None
    assert market_quote.compare_price({"status": "available", "base": "250"}, quote)["gap"] is None


def valuation():
    flows = list(map(Decimal, [100, 110, 120, 130, 140]))
    scenarios = [
        canonical(
            DCFModel().value(
                flows,
                Decimal(20),
                Decimal(10),
                MarketEquityShares(Decimal(10)),
                Decimal(w),
                Decimal(g),
            )
        )
        for w in ("0.09", "0.10", "0.11")
        for g in ("0.02", "0.025", "0.03")
    ]
    base = next(
        s["per_share"]
        for s in scenarios
        if s["wacc"] == "0.10000000" and s["terminal_growth"] == "0.02500000"
    )
    return {
        "dcf_projection": {
            "status": "available",
            "cashflows": list(map(str, flows)),
            "formula": "synthetic",
            "limitations": "synthetic fixture",
        },
        "source_valuation": {
            "basis_date": "2026-08-27",
            "inputs": {"balance:cash": {"value": "20"}, "balance:debt": {"value": "10"}},
            "shares": {"share_count": "10"},
        },
        "sensitivity": scenarios,
    }, base


def test_every_scenario_and_stored_base_are_reconciled_without_changing_formula():
    metadata, stored = valuation()
    before = copy.deepcopy(metadata)
    result = workbench.reconcile_valuation(metadata, stored)
    assert result["base"] == stored and len(result["scenarios"]) == 9
    assert metadata == before
    metadata["sensitivity"][0]["per_share"] = "0"
    with pytest.raises(ValueError, match="敏感度"):
        workbench.reconcile_valuation(metadata, stored)
    with pytest.raises(ValueError, match="基準"):
        workbench.reconcile_valuation(before, Decimal(stored) + Decimal("0.01"))


def test_missing_valuation_stays_unavailable_and_does_not_invent_zero():
    metadata, _ = valuation()
    result = workbench.reconcile_valuation(metadata, None)
    assert result["status"] == "unavailable" and result["base"] is None


def test_source_sidecars_are_refused_and_connection_is_readonly(tmp_path):
    path = tmp_path / "source.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("create table original (id integer)")
    before = workbench.file_hash(path)
    engine = workbench.readonly_engine(path)
    try:
        with engine.connect() as db, pytest.raises(Exception, match="readonly"):
            db.exec_driver_sql("insert into original values (1)")
    finally:
        engine.dispose()
    assert workbench.file_hash(path) == before
    (tmp_path / "source.sqlite-wal").write_bytes(b"pending")
    with pytest.raises(ValueError, match="sidecar"):
        workbench.source_preflight(path)


def test_raw_hash_is_checked_using_explicit_directory_and_not_historical_path(tmp_path):
    content = b"synthetic official disclosure"
    hash_ = hashlib.sha256(content).hexdigest()
    path = tmp_path / hash_
    path.write_bytes(content)
    doc = SimpleNamespace(
        id=1,
        content_hash=hash_,
        raw_path="/must/not/follow",
        source_url="https://nvidianews.nvidia.com/news/synthetic",
        source_provider="NVIDIA IR",
        retrieved_at=NOW,
        published_at=NOW,
    )
    db = SimpleNamespace(get=lambda *args: doc, scalars=lambda *args: [])
    assert workbench.verified_sources(db, {1}, tmp_path)[0]["official_disclosure"] is True
    path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="雜湊"):
        workbench.verified_sources(db, {1}, tmp_path)


def minimal_research():
    return {
        "current": {
            "valuation": {"status": "available", "base": "250", "basis_date": "2026-08-27"},
            "checkpoint": "2026-08-27T13:30:00+00:00",
        },
        "synthetic_only": True,
    }


def test_failed_manual_update_preserves_previous_snapshot_and_identical_replay(
    tmp_path, monkeypatch
):
    service = workbench.Workbench(tmp_path / "source.db", tmp_path / "raw", tmp_path / "isolated")
    monkeypatch.setattr(workbench, "build_research", lambda *args: minimal_research())
    monkeypatch.setattr(
        workbench,
        "fetch_quote",
        lambda *args: market_quote.parse_quote(quote_payload(), "2026-08-27", NOW),
    )
    first = service.update()
    assert service.update()["snapshot_id"] == first["snapshot_id"]
    pointer = (service.store / "current.json").read_bytes()

    def fail(*args):
        raise ValueError("synthetic source hash mismatch")

    monkeypatch.setattr(workbench, "build_research", fail)
    with pytest.raises(ValueError, match="hash mismatch"):
        service.update()
    assert (service.store / "current.json").read_bytes() == pointer
    loaded = service.load()
    assert loaded["snapshot_id"] == first["snapshot_id"]
    assert loaded["last_attempt"]["status"] == "failed"


def test_overlapping_update_and_tampered_saved_snapshot_fail_closed(tmp_path, monkeypatch):
    service = workbench.Workbench(tmp_path / "source.db", tmp_path / "raw", tmp_path / "isolated")
    service.lock.acquire()
    with pytest.raises(ValueError, match="另一個"):
        service.update()
    service.lock.release()
    monkeypatch.setattr(workbench, "build_research", lambda *args: minimal_research())
    monkeypatch.setattr(
        workbench, "fetch_quote", lambda *args: {"status": "unavailable", "price": None}
    )
    saved = service.update()
    (service.store / (saved["snapshot_id"] + ".json")).write_text("{}")
    with pytest.raises(ValueError, match="雜湊"):
        service.load()
    (service.store / "current.json").write_text(json.dumps({"snapshot_id": "../source.db"}))
    with pytest.raises(ValueError, match="指標"):
        service.load()
