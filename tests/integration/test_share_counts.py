from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from valuation_engine.db.schema import CorporateAction, Filing, ShareCountObservation
from valuation_engine.db.store import company, document
from valuation_engine.hardening.shares import (
    add_share_observation,
    cover_share_values,
    get_latest_known_shares,
    ingest_cover_shares,
    ingest_structured_shares,
)


def dt(value):
    return datetime.fromisoformat(value)


@pytest.fixture
def shares(db, tmp_path):
    co = company(db)

    def create(
        count,
        economic="2024-05-01",
        published="2024-05-22T20:20:00+00:00",
        available="2024-05-22T20:23:00+00:00",
        kind="sec_cover",
        suffix="a",
        **kwargs,
    ):
        source = document(
            db,
            tmp_path,
            suffix.encode(),
            url=f"https://example.test/{suffix}",
            company_id=co.id,
            provider="synthetic SEC",
            kind="test",
            published_at=dt(published),
        )
        return add_share_observation(
            db,
            source=source,
            share_count=D(count),
            shares_as_of_date=date.fromisoformat(economic),
            published_at=dt(published),
            available_at=dt(available),
            source_type=kind,
            basis_date=date.fromisoformat(economic),
            **kwargs,
        )[0]

    return create


def test_future_share_publication_is_not_visible(db, shares):
    old = shares("100")
    shares(
        "999",
        economic="2024-05-20",
        published="2024-05-24T20:20:00+00:00",
        available="2024-05-24T20:23:00+00:00",
        suffix="future",
    )
    assert get_latest_known_shares(db, 1, dt("2024-05-22T20:22:59+00:00")) is None
    chosen = get_latest_known_shares(db, 1, dt("2024-05-23T13:30:00+00:00"))
    assert chosen["observation_id"] == old.id and chosen["share_count"] == 100
    assert chosen["available_at"] <= dt("2024-05-23T13:30:00+00:00")
    assert get_latest_known_shares(db, 1, dt("2024-05-24T20:23:00+00:00"))["share_count"] == 999


def test_share_freshness_then_source_priority_and_conflict(db, shares):
    shares("90", economic="2024-04-01", suffix="older")
    shares("100", kind="official_disclosure", suffix="official")
    cover = shares("101", suffix="cover")
    at = dt("2024-05-23T13:30:00+00:00")
    assert get_latest_known_shares(db, 1, at)["observation_id"] == cover.id
    shares("102", suffix="conflict")
    assert get_latest_known_shares(db, 1, at) is None


def test_share_immutability_and_weighted_average_rejected(db, shares):
    with pytest.raises(ValueError, match="Weighted-average"):
        shares("100", taxonomy_concept="us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding")
    row = shares("100")
    db.commit()
    with pytest.raises(DBAPIError, match="immutable record"):
        db.execute(
            text("UPDATE share_count_observations SET confidence='low' WHERE id=:id"),
            {"id": row.id},
        )
    db.rollback()


def test_two_split_share_price_marketcap_invariance(db, shares, tmp_path):
    row = shares(
        "5000000",
        economic="2020-05-01",
        published="2020-05-20T20:20:00+00:00",
        available="2020-05-20T20:23:00+00:00",
    )
    for day, ratio in ((date(2021, 7, 20), D(4)), (date(2024, 6, 10), D(10))):
        source = document(
            db,
            tmp_path,
            str(day).encode(),
            url=f"https://example.test/split/{day}",
            company_id=1,
            provider="synthetic",
            kind="test",
            published_at=None,
        )
        db.add(
            CorporateAction(
                identity_key=str(day),
                company_id=1,
                action_type="split",
                split_date=day,
                effective_date=day - timedelta(days=1),
                ratio_numerator=ratio,
                ratio_denominator=D(1),
                adjustment_factor=ratio,
                announced_at=dt("2020-01-01T00:00:00+00:00"),
                source_document_id=source.id,
                metadata_json={},
            )
        )
    db.flush()
    before = get_latest_known_shares(db, 1, dt("2020-06-01T13:30:00+00:00"))
    middle = get_latest_known_shares(db, 1, dt("2022-06-01T13:30:00+00:00"))
    after = get_latest_known_shares(db, 1, dt("2025-06-01T13:30:00+00:00"))
    assert (
        before["share_count"] * D(400)
        == middle["share_count"] * D(100)
        == after["share_count"] * D(10)
    )
    original = get_latest_known_shares(
        db, 1, dt("2025-06-01T13:30:00+00:00"), basis_date=date(2020, 5, 1)
    )
    assert original["share_count"] == row.share_count == D(5000000)


def cover_html(unit="shares", member="", count="1,234.5", scale="6"):
    return f'''<html><body><xbrli:context id="c"><xbrli:entity><xbrli:identifier>0001045810</xbrli:identifier>{member}</xbrli:entity><xbrli:period><xbrli:instant>2023-05-19</xbrli:instant></xbrli:period></xbrli:context>
    <xbrli:unit id="u"><xbrli:measure>xbrli:{unit}</xbrli:measure></xbrli:unit>
    <ix:nonFraction name="dei:EntityCommonStockSharesOutstanding" contextRef="c" unitRef="u" scale="{scale}" decimals="-3" format="ixt:num-dot-decimal">{count}</ix:nonFraction>
    <ix:nonFraction name="us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding" contextRef="c" unitRef="u">9999</ix:nonFraction></body></html>'''.encode()


@pytest.mark.parametrize(
    "unit,member",
    [("USD", ""), ("shares", "<xbrldi:explicitMember>UnknownClass</xbrldi:explicitMember>")],
)
def test_cover_rejects_wrong_unit_and_unmapped_class(unit, member):
    values, errors = cover_share_values(cover_html(unit=unit, member=member), "0001045810")
    assert values == [] and errors


def test_cover_archive_ingestion_and_availability(db, tmp_path):
    co = company(db)
    filing = Filing(
        company_id=co.id,
        accession_number="synthetic-cover",
        form_type="10-Q",
        filing_date=date(2023, 5, 24),
        period_end=date(2023, 4, 30),
        accepted_timestamp=dt("2023-05-24T21:00:00+00:00"),
        source_url="https://example.test/cover",
    )
    db.add(filing)
    db.flush()
    source = document(
        db,
        tmp_path,
        cover_html(),
        url=filing.source_url,
        company_id=co.id,
        provider="SEC",
        kind="SEC primary filing",
        published_at=None,
        filing_id=filing.id,
    )
    first = ingest_cover_shares(db, co.id)
    second = ingest_cover_shares(db, co.id)
    assert first["created"] == 1 and first["unavailable"] == []
    assert second["created"] == 0 and second["skipped"] == 1
    before = dt("2023-05-24T21:02:59+00:00")
    assert get_latest_known_shares(db, co.id, before) is None
    result = get_latest_known_shares(db, co.id, before + timedelta(seconds=1))
    assert result["share_count"] == D("1234500000")
    assert result["source_document_id"] == source.id
    assert result["shares_as_of_date"] == date(2023, 5, 19)
    # A later accession's older comparative is not treated as its current share count.
    rejected = ingest_structured_shares(
        db,
        filing,
        source,
        [
            {
                "metric": "period_end_shares",
                "taxonomy": "us-gaap",
                "concept": "CommonStockSharesOutstanding",
                "obs": {"end": "2022-04-30", "val": 999},
            }
        ],
    )
    assert rejected["created"] == 0 and len(rejected["unavailable"]) == 1
    assert len(list(db.scalars(select(ShareCountObservation)))) == 1


def test_marketcap_uses_pit_shares_and_ev_tracks_missing_debt(db, add, shares):
    from valuation_engine.db.schema import MarketPrice
    from valuation_engine.hardening.basis import build_price_bases
    from valuation_engine.hardening.valuation import historical_value_at
    from valuation_engine.normalization.quarterly import PointInTimeRepository

    at = dt("2024-05-23T13:30:00+00:00")
    for fy, fq in ((2024, 2), (2024, 3), (2024, 4), (2025, 1)):
        for metric, count in (("revenue", 100), ("ocf", 30), ("capex", 10)):
            add(
                metric,
                count,
                fy=fy,
                fq=fq,
                available="2024-05-22T20:20:00+00:00",
                url=f"https://example.test/{fy}/{fq}",
            )
    add("diluted_shares", 999, fy=2025, fq=1, unit="shares", available="2024-05-22T20:20:00+00:00")
    add(
        "cash",
        10,
        fy=2024,
        fq=4,
        kind="instant",
        available="2024-02-22T20:20:00+00:00",
        url="https://example.test/previous-cash",
    )
    # Debt is only disclosed later, so it must not be treated as zero or become visible early.
    add(
        "debt",
        7,
        fy=2025,
        fq=1,
        kind="instant",
        available="2024-05-24T20:20:00+00:00",
        url="https://example.test/later-debt",
    )
    db.add(
        MarketPrice(
            company_id=1,
            ticker="NVDA",
            timestamp=at,
            available_at=at + timedelta(hours=6, minutes=30),
            price_type="daily_unadjusted",
            open=D(100),
            high=D(110),
            low=D(90),
            close=D(105),
            adjusted_close=None,
            volume=100,
            currency="USD",
            provider="synthetic",
            retrieved_at=at,
            content_hash="synthetic-marketcap-price",
        )
    )
    db.flush()
    build_price_bases(db, 1)
    repo = PointInTimeRepository(db, 1)
    q = repo.quarter(2025, 1, at)
    missing = historical_value_at(db, repo, q, at)
    assert missing.market_cap is None  # Weighted average is not a fallback.
    shares("120", economic="2024-05-01")
    shares(
        "500",
        economic="2024-05-21",
        published="2024-05-24T20:20:00+00:00",
        available="2024-05-24T20:23:00+00:00",
        suffix="future-count",
    )
    value = historical_value_at(db, repo, q, at)
    assert value.market_cap == D(12000)
    assert value.enterprise_value is None
    assert value.metadata_json["ev_missing_components"] == ["debt"]
    assert value.metadata_json["inputs"]["balance:cash"]["carried_forward"] is True
    assert abs(value.fcf_yield - D(80) / D(12000)) < D(".00000001")
    assert value.metadata_json["shares"]["share_count"] == "120.00000000"
    assert historical_value_at(db, repo, q, at).id == value.id
