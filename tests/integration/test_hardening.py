from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from valuation_engine.cli.main import app
from valuation_engine.db.schema import CorporateAction, MarketPrice, PriceBasis, SourceDocument
from valuation_engine.db.store import company, document, read_document
from valuation_engine.hardening.availability import AvailabilityResolver, add_evidence
from valuation_engine.hardening.basis import (
    SplitBasis,
    build_price_bases,
    get_price_as_reported,
    get_split_adjusted_price,
)
from valuation_engine.hardening.reconcile import reconcile
from valuation_engine.hardening.valuation import historical_value_at
from valuation_engine.normalization.quarterly import PointInTimeRepository
from valuation_engine.time import calculate_next_tradable_timestamp


def dt(s):
    return datetime.fromisoformat(s)


def test_conflict_review_is_scoped_and_does_not_approve_selected_candidates(db, add):
    from valuation_engine.hardening.quality import review_quality

    original = add("revenue", 100)
    revised = add(
        "revenue", 110, url="https://example.test/revision", available="2024-05-24T20:20:00Z"
    )
    at = dt("2025-01-01T00:00:00Z")
    assert review_quality(db, 1, at)[0]["blocking"] is True
    unaffected = review_quality(db, 1, at, snapshot_fact_ids={"FY2024-Q1": [original.id]})[0]
    assert unaffected["blocking"] is False
    assert unaffected["resolution"] == "unresolved_but_excluded_from_reviewed_snapshots"
    assert unaffected["evidence"]["candidate_fact_ids"] == [revised.id]
    affected = review_quality(db, 1, at, snapshot_fact_ids={"FY2024-Q1": [revised.id]})[0]
    assert affected["blocking"] is True
    assert affected["evidence"]["affected_snapshot_fact_ids"] == {"FY2024-Q1": [revised.id]}
    assert review_quality(db, 1, at)[0]["blocking"] is True


@pytest.mark.parametrize("corrupted", [False, True])
def test_relocated_source_hash_verification(db, tmp_path, corrupted):
    original, relocated = tmp_path / "original", tmp_path / "relocated"
    source = document(
        db,
        original,
        b"archived release",
        url="https://example.test/relocated",
        company_id=company(db).id,
        provider="synthetic",
        kind="test",
        published_at=None,
    )
    relocated.mkdir()
    (original / source.content_hash).rename(relocated / source.content_hash)
    if corrupted:
        (relocated / source.content_hash).write_bytes(b"changed release")
        with pytest.raises(ValueError, match="hash mismatch"):
            read_document(source, relocated)
    else:
        assert read_document(source, relocated) == b"archived release"
    assert source.raw_path == str((original / source.content_hash).resolve())


@pytest.mark.parametrize(
    "information,expected",
    [
        ("2024-05-22T08:00:00-04:00", "2024-05-22T09:30:00-04:00"),
        ("2024-05-22T12:00:00-04:00", "2024-05-23T09:30:00-04:00"),
        ("2024-05-22T16:20:00-04:00", "2024-05-23T09:30:00-04:00"),
        ("2024-05-25T10:00:00-04:00", "2024-05-28T09:30:00-04:00"),
        ("2024-07-04T10:00:00-04:00", "2024-07-05T09:30:00-04:00"),
        ("2024-07-03T13:01:00-04:00", "2024-07-05T09:30:00-04:00"),
        ("2024-03-08T16:20:00-05:00", "2024-03-11T09:30:00-04:00"),
        ("2024-11-01T16:20:00-04:00", "2024-11-04T09:30:00-05:00"),
        ("2024-11-29T13:00:00-05:00", "2024-12-02T09:30:00-05:00"),
    ],
)
def test_tradable_contract(information, expected):
    assert calculate_next_tradable_timestamp(dt(information)) == dt(expected)


def test_minute_evidence_scope_pit_and_exact(db, add):
    f = add("revenue", 100, available="2023-05-25T04:00:00+00:00")
    sec = add(
        "cash",
        20,
        kind="instant",
        available="2023-05-25T18:00:00+00:00",
        url="https://example.test/filing",
    )
    doc = db.get(SourceDocument, f.source_document_id)
    at = dt("2023-05-24T16:20:00-04:00")
    add_evidence(db, doc, doc, at, "minute", f.available_at, ("financial_fact",))
    repo = PointInTimeRepository(db, 1)
    assert repo.quarter(2024, 1, at - timedelta(microseconds=1)) is None
    assert repo.quarter(2024, 1, at + timedelta(seconds=59)) is None
    q = repo.quarter(2024, 1, at + timedelta(minutes=1))
    assert q.value("revenue") == 100 and q.value("cash") is None
    assert q.metrics["revenue"].metadata["timestamp_precision"] == "minute"
    assert AvailabilityResolver(db, "guidance").time(f) == f.available_at
    add_evidence(db, doc, doc, at, "exact", f.available_at, ("financial_fact",))
    assert repo.quarter(2024, 1, at).value("revenue") == 100
    assert sec.available_at > at


def split_fixture(db, tmp_path):
    co = company(db)
    doc = document(
        db,
        tmp_path,
        b"synthetic split",
        url="https://example.test/split",
        company_id=co.id,
        provider="synthetic",
        kind="test",
        published_at=None,
    )
    db.add(
        CorporateAction(
            identity_key="split-test",
            company_id=co.id,
            action_type="split",
            split_date=date(2024, 6, 10),
            effective_date=date(2024, 6, 7),
            ratio_numerator=D(10),
            ratio_denominator=D(1),
            adjustment_factor=D(10),
            announced_at=dt("2024-05-22T20:20:00+00:00"),
            source_document_id=doc.id,
            metadata_json={},
        )
    )
    db.flush()
    return co


def bar_fixture(db, co):
    row = MarketPrice(
        company_id=co.id,
        ticker="NVDA",
        timestamp=dt("2024-05-23T13:30:00+00:00"),
        available_at=dt("2024-05-23T20:00:00+00:00"),
        price_type="daily_split_adjusted_current_vintage",
        open=D(100),
        high=D(110),
        low=D(90),
        close=D(105),
        adjusted_close=D(104),
        volume=100,
        currency="USD",
        provider="synthetic",
        retrieved_at=dt("2024-06-11T20:00:00+00:00"),
        content_hash="test",
    )
    db.add(row)
    db.flush()
    return row


def test_price_field_availability_and_split_separation(db, tmp_path):
    co = split_fixture(db, tmp_path)
    bar = bar_fixture(db, co)
    build_price_bases(db, co.id)
    assert build_price_bases(db, co.id) == {"created": 0, "skipped": 1}
    quote = get_price_as_reported(db, co.id, bar.timestamp)
    assert quote["value"] == D(1000) and quote["origin"] == "research_reconstructed"
    assert get_price_as_reported(db, co.id, bar.timestamp, "close") is None
    assert get_price_as_reported(db, co.id, bar.timestamp, require_observed=True) is None
    adjusted = get_split_adjusted_price(db, co.id, bar.timestamp, date(2024, 6, 10))
    assert adjusted["value"] == D(100)
    row = db.scalar(select(PriceBasis))
    assert row.adjusted_close == D(104) and row.adjusted_open is None
    split = SplitBasis(db, co.id)
    assert split.per_share(D(40), date(2024, 5, 22), date(2024, 6, 10)) == 4
    assert split.shares(D(5), date(2024, 5, 22), date(2024, 6, 10)) == 50
    assert split.factor(date(2024, 6, 10), date(2024, 5, 22)) == D(".1")


def test_historical_pe_marketcap_regression_and_unknown_basis(db, tmp_path, add):
    from valuation_engine.hardening.shares import add_share_observation

    co = split_fixture(db, tmp_path)
    bar = bar_fixture(db, co)
    build_price_bases(db, co.id)
    source = document(
        db,
        tmp_path / "shares",
        b"synthetic official share disclosure",
        url="https://example.test/current-shares",
        company_id=co.id,
        provider="synthetic",
        kind="test",
        published_at=dt("2024-05-22T20:20:00+00:00"),
    )
    add_share_observation(
        db,
        source=source,
        share_count=D(100),
        shares_as_of_date=date(2024, 5, 20),
        published_at=dt("2024-05-22T20:20:00+00:00"),
        available_at=dt("2024-05-22T20:21:00+00:00"),
        source_type="official_disclosure",
        basis_date=date(2024, 5, 20),
    )
    # Four original pre-split quarters, each EPS=10; price at open=1000 => PE=25.
    for fy, fq in [(2024, 2), (2024, 3), (2024, 4), (2025, 1)]:
        for metric, value, unit, kind in [
            ("revenue", 100, "USD", "quarter"),
            ("eps_diluted", 10, "USD/shares", "quarter"),
            ("fcf", 20, "USD", "quarter"),
            ("operating_income", 30, "USD", "quarter"),
            ("cash", 10, "USD", "instant"),
            ("debt", 5, "USD", "instant"),
            ("period_end_shares", 100, "shares", "instant"),
        ]:
            add(
                metric,
                value,
                fy=fy,
                fq=fq,
                available="2024-05-22T20:20:00+00:00",
                unit=unit,
                kind=kind,
                url=f"https://example.test/{fy}/{fq}",
            )
            # Explicit basis is attached at insertion via test source evidence.
            # Synthetic source has no inferred basis. Test a pure Quarter copy with explicit basis.
    repo = PointInTimeRepository(db, co.id)
    quarters = {}
    for fy, fq in [(2024, 2), (2024, 3), (2024, 4), (2025, 1)]:
        q = repo.quarter(fy, fq, bar.timestamp)
        quarters[(fy, fq)] = q.model_copy(
            update={
                "metrics": {
                    k: o.model_copy(
                        update={"metadata": {**o.metadata, "share_basis_date": "2024-05-22"}}
                    )
                    for k, o in q.metrics.items()
                }
            }
        )

    class VerifiedRepo:
        def quarter(self, fy, fq, as_of):
            return quarters.get((fy, fq))

    q = quarters[(2025, 1)]
    row = historical_value_at(db, VerifiedRepo(), q, bar.timestamp)
    assert row.trailing_pe == D(25)
    assert row.market_cap == D(100000)
    assert row.enterprise_value == D(99995)
    assert row.fcf_yield == D(".0008")
    assert row.fy1_pe is None and row.fy2_pe is None
    # The split changes price and EPS by the same factor: PE and cap are invariant.
    post = MarketPrice(
        company_id=co.id,
        ticker="NVDA",
        timestamp=dt("2024-06-11T13:30:00+00:00"),
        available_at=dt("2024-06-11T20:00:00+00:00"),
        price_type="daily_unadjusted",
        open=D(100),
        high=D(110),
        low=D(90),
        close=D(105),
        adjusted_close=None,
        volume=1000,
        currency="USD",
        provider="synthetic",
        retrieved_at=dt("2024-06-12T00:00:00+00:00"),
        content_hash="post-split",
    )
    db.add(post)
    db.flush()
    build_price_bases(db, co.id)
    postq = q.model_copy(update={"as_of": post.timestamp})
    postvalue = historical_value_at(db, VerifiedRepo(), postq, post.timestamp)
    assert postvalue.trailing_pe == row.trailing_pe == 25
    assert postvalue.market_cap == row.market_cap
    assert postvalue.metadata_json["eps_ttm_normalized"] == "4.00000000"
    bad = q.model_copy(
        update={"metrics": {k: o.model_copy(update={"metadata": {}}) for k, o in q.metrics.items()}}
    )
    result = historical_value_at(db, repo, bad, bar.timestamp)
    assert result.trailing_pe is None and result.market_cap == D(100000)


def test_reconciliation_preserves_both_sources(db, add):
    ir = add("revenue", 100, url="https://example.test/ir", provider="NVIDIA IR")
    sec = add(
        "revenue",
        101,
        url="https://example.test/sec",
        available="2023-05-25T12:00:00+00:00",
        provider="SEC",
    )
    assert reconcile(db, 1) == {"conflict": 1}
    assert reconcile(db, 1) == {"conflict": 1}
    assert ir.value == 100 and sec.value == 101
    repo = PointInTimeRepository(db, 1)
    assert repo.quarter(2024, 1, dt("2023-05-26T00:00:00+00:00")).value("revenue") == 100
    assert (
        repo.quarter(2024, 1, dt("2023-05-26T00:00:00+00:00"), "latest_restated").value("revenue")
        == 101
    )


def test_configure_sec_private_local_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["configure-sec"], input="Fixture Research\nqa@example.test\n")
    assert result.exit_code == 0, result.output
    path = tmp_path / ".env"
    assert path.stat().st_mode & 0o777 == 0o600
    assert "SEC_USER_AGENT=" in path.read_text()


def test_two_split_round_trip_and_immutability(db, tmp_path):
    co = split_fixture(db, tmp_path)
    source = db.scalar(select(SourceDocument))
    db.add(
        CorporateAction(
            identity_key="earlier-split",
            company_id=co.id,
            action_type="split",
            split_date=date(2021, 7, 20),
            effective_date=date(2021, 7, 19),
            ratio_numerator=D(4),
            ratio_denominator=D(1),
            adjustment_factor=D(4),
            announced_at=dt("2021-05-21T20:00:00+00:00"),
            source_document_id=source.id,
            metadata_json={},
        )
    )
    db.flush()
    split = SplitBasis(db, co.id)
    assert split.factor(date(2020, 1, 1), date(2026, 1, 1)) == 40
    assert split.per_share(D(80), date(2020, 1, 1), date(2026, 1, 1)) == 2
    assert split.shares(D(100), date(2020, 1, 1), date(2026, 1, 1)) == 4000
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError, match="immutable record"):
        with db.begin_nested():
            db.execute(text("UPDATE corporate_actions SET ratio_numerator = 2"))


def test_live_postgresql_migration_contract():
    import os

    from sqlalchemy import create_engine, inspect, text

    url = os.environ.get("QVE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Executed by scripts/validate_postgres_m11.py against isolated PostgreSQL")
    e = create_engine(url)
    with e.connect() as c:
        assert (
            c.execute(text("select version_num from public.alembic_version")).scalar()
            == "0008_ai_analyst"
        )
        tables = set(inspect(c).get_table_names(schema="public"))
        assert {
            "financial_facts",
            "availability_evidence",
            "corporate_actions",
            "price_bases",
        } <= tables
        assert "future_outcomes" not in tables
    e.dispose()


@pytest.mark.parametrize(
    "input_value,stored_value",
    [
        ("9007199254740993.12345678", "9007199254740993.12345678"),
        ("9999999999999999999999.99999999", "9999999999999999999999.99999999"),
        ("0.123456785", "0.12345678"),
        ("0.123456795", "0.12345680"),
    ],
)
def test_exact_decimal_storage_matches_backends(db, add, input_value, stored_value):
    row = add("revenue", input_value)
    identifier = row.id
    db.flush()
    db.expire_all()
    from valuation_engine.db.schema import FinancialFact

    assert db.get(FinancialFact, identifier).value == D(stored_value)


def test_numeric_migration_preserves_records_and_guards(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    path = tmp_path / "migrate-decimal.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(cfg, "0002_hardening")
    e = create_engine(f"sqlite:///{path}")
    with e.begin() as c:
        c.execute(
            text(
                "INSERT INTO companies (id,created_at,updated_at,ticker,company_name,cik,exchange,currency,valuation_archetype,archetype_confidence) VALUES (1,'2024-01-01','2024-01-01','NVDA','Fixture','0001045810','NASDAQ','USD','test',0.123456)"
            )
        )
    command.upgrade(cfg, "head")
    audit = cfg.attributes["numeric_storage_audit"]
    assert all(r["before_hash"] == r["after_hash"] for r in audit)
    with e.connect() as c:
        assert (
            c.execute(text("select typeof(archetype_confidence) from companies")).scalar() == "text"
        )
        assert c.exec_driver_sql("pragma foreign_key_check").fetchall() == []
        guards = c.execute(
            text(
                "select count(*) from sqlite_master where type='trigger' and name like 'immutable_financial_facts_%'"
            )
        ).scalar()
        assert guards == 2
    e.dispose()
