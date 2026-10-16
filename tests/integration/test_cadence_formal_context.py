"""End-to-end cadence consumption of actual producers on a temporary synthetic DB."""

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_research import populate
from test_research import synthetic as synthetic

from valuation_engine.cadence.pipeline import CadencePipelineConfig, QuarterlyCadencePipeline
from valuation_engine.db.schema import MarketPrice
from valuation_engine.hardening.basis import build_price_bases
from valuation_engine.hardening.shares import add_share_observation
from valuation_engine.regime.confidence import POLICY, snapshot_contract
from valuation_engine.regime.service import replay
from valuation_engine.research.service import build_forecast
from valuation_engine.research.valuation import build_valuation
from valuation_engine.time import calculate_next_tradable_timestamp


def test_cadence_reads_produced_formal_cohort_without_replay(db, synthetic, tmp_path, monkeypatch):
    if db.get_bind().dialect.name != "sqlite":
        pytest.skip("Cadence currently supports read-only SQLite")
    path = Path(db.get_bind().url.database)
    assert path.is_relative_to(tmp_path)
    releases = populate(synthetic, count=9)
    released, source = releases[-1]
    at = calculate_next_tradable_timestamp(released)
    add_share_observation(
        db,
        source=source,
        share_count=Decimal(9000),
        shares_as_of_date=released.date(),
        published_at=released,
        available_at=released,
        source_type="official_disclosure",
        basis_date=released.date(),
    )
    db.add(
        MarketPrice(
            company_id=1,
            ticker="NVDA",
            timestamp=at,
            available_at=at + timedelta(hours=7),
            price_type="daily_unadjusted",
            open=100,
            high=110,
            low=90,
            close=105,
            volume=100,
            currency="USD",
            provider="synthetic",
            retrieved_at=at,
            content_hash="synthetic-price",
        )
    )
    db.flush()
    build_price_bases(db, 1)
    runs = [
        build_forecast(db, 1, calculate_next_tradable_timestamp(release))
        for release, _ in releases[-5:]
    ]
    run = runs[-1]
    records, _, packs = replay(db, 1, run.forecast_as_of, POLICY)
    valuation = build_valuation(db, run)
    expected = snapshot_contract(records[-1])
    checkpoint = run.forecast_as_of
    quarter = run.metadata_json["anchor"]
    valuation_id, snapshot_id = valuation.id, records[-1].id
    db.commit()
    forbidden = Mock(side_effect=AssertionError("Cadence must never rebuild or replay"))
    monkeypatch.setattr("valuation_engine.regime.service.replay", forbidden)
    monkeypatch.setattr("valuation_engine.research.service.build_forecast", forbidden)
    monkeypatch.setattr("valuation_engine.research.valuation.build_valuation", forbidden)
    config = CadencePipelineConfig(
        fiscal_year=int(quarter[2:6]),
        fiscal_quarter=int(quarter[-1]),
        as_of_date=checkpoint.date().isoformat(),
        checkpoint_timestamp=checkpoint,
        qve_db_path=path,
        candidate_db_path=tmp_path / "absent-candidate.db",
    )
    before = path.read_bytes()
    result = QuarterlyCadencePipeline(config).run()
    actual = result.receipt_data["decision"]["regime_summary"]
    assert all(actual[key] == value for key, value in expected.items())
    assert actual["input_lineage"] == packs[-1]
    assert actual["snapshot_id"] == snapshot_id
    assert result.receipt_data["formal_context"]["valuation_id"] == valuation_id
    assert path.read_bytes() == before
    forbidden.assert_not_called()
