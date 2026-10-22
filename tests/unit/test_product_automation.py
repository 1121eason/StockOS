"""Product persistence/failure contracts on synthetic inputs, never formal data."""

import copy
import hashlib
import json
import time
from datetime import UTC, datetime

import pytest

from valuation_engine.research import discovery, product
from valuation_engine.research.product_store import ProductStore

URL = "https://nvidianews.nvidia.com/news/synthetic-official-announcement"
ARTICLE = b'<html><h1>Synthetic announcement</h1><time>October 21, 2026</time><div class="article-body"><p>Document evidence.</p></div></html>'


@pytest.fixture
def service(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No real network or formal data in synthetic product tests")

    monkeypatch.setattr(discovery, "download", forbidden)
    monkeypatch.setattr(product, "fetch_quote", forbidden)
    monkeypatch.setattr(product, "build_research", forbidden)
    return product.Product(tmp_path / "formal.db", tmp_path / "raw", tmp_path / "product")


def research():
    return {
        "ticker": "NVDA",
        "verified_at": "2026-10-21T01:00:00+00:00",
        "current": {
            "quarter": "FY2027-Q2",
            "checkpoint": "2026-08-27T13:30:00+00:00",
            "valuation": {"status": "available", "base": "250", "basis_date": "2026-08-27"},
        },
        "ai": {"status": "pending_acceptance", "affects_valuation": False},
    }


def quote(price="200"):
    return {
        "status": "available",
        "price": price,
        "currency": "USD",
        "ticker": "NVDA",
        "valuation_basis_date": "2026-08-27",
        "split_factor_since_valuation": "1",
        "quoted_at": datetime.now(UTC).isoformat(),
    }


def job(kind, payload=None):
    return {"kind": kind, "payload": payload or {}}


def test_store_reopen_does_not_rewrite_database_or_downgrade_schema(service):
    before = hashlib.sha256(service.store.path.read_bytes()).hexdigest()
    ProductStore(service.store.root)
    assert hashlib.sha256(service.store.path.read_bytes()).hexdigest() == before
    with service.store.connect() as db:
        db.execute("PRAGMA user_version=2")
    with pytest.raises(ValueError, match="unsupported_product_store_version"):
        ProductStore(service.store.root)
    with service.store.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_repeated_schedules_and_restart_do_not_duplicate_jobs(service):
    at = time.time()
    service.schedule(at)
    service.schedule(at)
    reopened = ProductStore(service.store.root)
    assert len(reopened.jobs()) == 3
    running = reopened.claim(at)
    assert running["attempts"] == 1
    reopened.recover(at + 1)
    retry = reopened.claim(at + 1)
    assert retry["id"] == running["id"] and retry["attempts"] == 2


def test_bounded_retry_keeps_attempts_across_restart(service):
    store = service.store
    store.enqueue("COLLECT_QUOTES", "same", {}, 10)
    for expected, at in enumerate((10, 1000, 2000), 1):
        claimed = store.claim(at)
        assert claimed["attempts"] == expected
        store.finish(claimed, at, error="ValueError")
        store = ProductStore(store.root)
    assert store.claim(9999) is None
    assert store.jobs()[0]["status"] == "Failed"
    assert len(store.alerts()) == 1


def test_three_interrupted_attempts_cannot_retry_forever(service):
    store = service.store
    store.enqueue("COLLECT_QUOTES", "same", {}, 0)
    for at in range(3):
        assert store.claim(at)
        store.recover(at + 1)
    assert store.claim(4) is None
    assert store.jobs()[0]["status"] == "Failed"


def test_research_is_immutable_and_price_updates_do_not_republish_it(service, monkeypatch):
    monkeypatch.setattr(product, "build_research", lambda *a: research())
    at = time.time()
    first = service.execute(job("VERIFY_RESEARCH"), at)
    before = service.store.artifact(first)
    for value in ("200", "220"):
        monkeypatch.setattr(product, "fetch_quote", lambda *a, v=value: quote(v))
        service.execute(job("COLLECT_QUOTES"), at)
    loaded = service.load()
    assert loaded["snapshot_id"] == first
    assert loaded["research"]["current"]["valuation"]["base"] == "250"
    assert loaded["research"]["quote"]["price"] == "220"
    assert service.store.artifact(first) == before
    assert len(service.store.history("research")) == 1
    assert len(service.store.alerts()) == 1
    assert loaded["target_valuation"]["base"] is None
    assert loaded["target_valuation"]["target_at"] is None


def test_same_research_recheck_does_not_duplicate_publication_or_alert(service, monkeypatch):
    data = research()
    monkeypatch.setattr(product, "build_research", lambda *a: copy.deepcopy(data))
    first = service.execute(job("VERIFY_RESEARCH"), 100)
    data["verified_at"] = "2026-10-22T01:00:00+00:00"
    assert service.execute(job("VERIFY_RESEARCH"), 200) == first
    assert len(service.store.history("research")) == len(service.store.alerts()) == 1


def test_failed_research_preserves_previous_and_quote_channel_continues(service, monkeypatch):
    monkeypatch.setattr(product, "build_research", lambda *a: research())
    first = service.execute(job("VERIFY_RESEARCH"), time.time())

    def fail(*args):
        raise ValueError("source conflict")

    monkeypatch.setattr(product, "build_research", fail)
    with pytest.raises(ValueError):
        service.execute(job("VERIFY_RESEARCH"), time.time())
    monkeypatch.setattr(product, "fetch_quote", lambda *a: quote())
    service.execute(job("COLLECT_QUOTES"), time.time())
    assert service.load()["snapshot_id"] == first
    assert service.load()["research"]["quote"]["price"] == "200"


def test_quote_failure_keeps_previous_price_but_disables_current_gap(service, monkeypatch):
    monkeypatch.setattr(product, "build_research", lambda *a: research())
    monkeypatch.setattr(product, "fetch_quote", lambda *a: quote())
    service.execute(job("VERIFY_RESEARCH"), time.time())
    service.execute(job("COLLECT_QUOTES"), time.time())
    monkeypatch.setattr(product, "fetch_quote", lambda *a: {"status": "unavailable", "price": None})
    with pytest.raises(ValueError):
        service.execute(job("COLLECT_QUOTES"), time.time())
    data = service.load()["research"]
    assert data["quote"]["price"] == "200"
    assert data["quote"]["status"] == "stale"
    assert data["price_comparison"]["gap"] is None


def test_wrong_share_basis_cannot_create_a_gap(service, monkeypatch):
    monkeypatch.setattr(product, "build_research", lambda *a: research())
    service.execute(job("VERIFY_RESEARCH"), time.time())
    bad = {**quote(), "valuation_basis_date": "2020-01-01"}
    service.store.publish("quote", "wrong", bad, time.time(), pointer="quote")
    assert service.load()["research"]["price_comparison"]["gap"] is None


def test_source_versions_preserve_raw_bytes_and_deduplicate_repeat_notifications(
    service, monkeypatch
):
    monkeypatch.setattr(discovery, "download", lambda *a, **kw: ARTICLE)
    j = job("INGEST_DOCUMENT", {"url": URL, "index_hash": "a" * 64})
    at = datetime(2026, 10, 22, tzinfo=UTC).timestamp()
    first = service.execute(j, at)
    assert service.execute(j, at + 3600) == first
    assert len(service.store.alerts()) == 1
    # Transport-only changes are archived but do not generate another event alert.
    variant = ARTICLE.replace(b"<html>", b'<html data-render="2">')
    monkeypatch.setattr(discovery, "download", lambda *a, **kw: variant)
    second = service.execute(j, at + 7200)
    assert first != second
    assert service.store.artifact(second)["payload"]["supersedes"] == first
    assert len(service.store.alerts()) == 1
    for raw in (ARTICLE, variant):
        assert (service.store.root / "raw" / hashlib.sha256(raw).hexdigest()).read_bytes() == raw
    corrected = variant.replace(b"Document evidence.", b"Corrected source evidence.")
    monkeypatch.setattr(discovery, "download", lambda *a, **kw: corrected)
    service.execute(j, at + 10000)
    assert len(service.store.alerts()) == 2
    assert len(service.load()["events"]) == 1


def test_published_artifact_tampering_is_rejected(service):
    identity = service.store.publish("research", "test", research(), 1, pointer="research")
    with service.store.connect() as db:
        db.execute(
            "UPDATE artifacts SET payload=? WHERE id=?", (json.dumps({"fake": True}), identity)
        )
    with pytest.raises(ValueError, match="hash_mismatch"):
        service.load()


def test_many_revisions_of_one_announcement_do_not_hide_other_current_documents(service):
    other = "https://nvidianews.nvidia.com/news/other-announcement"
    first = service.store.publish(
        "source_document", "other", {"url": other, "title": "Other"}, 0, pointer="source:" + other
    )
    for version in range(55):
        latest = service.store.publish(
            "source_document",
            str(version),
            {"url": URL, "title": str(version)},
            version + 1,
            pointer="source:" + URL,
        )
    events = service.load()["events"]
    assert {event["id"] for event in events} == {first, latest}
    assert len(service.store.history("source_document")) == 40


@pytest.mark.parametrize(
    "url",
    [
        "http://nvidianews.nvidia.com/news/test",
        "https://evil.test/news/test",
        "https://nvidianews.nvidia.com@evil.test/news/test",
        "https://nvidianews.nvidia.com:8443/news/test",
        "https://user:password@nvidianews.nvidia.com/news/test",
        "https://nvidianews.nvidia.com/_gallery/test",
    ],
)
def test_unapproved_source_destinations_are_rejected(url):
    with pytest.raises(ValueError):
        discovery.official_url(url)


def test_discovery_strips_tracking_and_rejects_external_or_executable_links():
    body = b'<a href="/news/test?track=1">one</a><a href="/news/test?track=2">two</a><a href="https://evil.test/news/test">bad</a><a href="javascript:alert(1)">bad</a>'
    assert discovery.discover(body) == ["https://nvidianews.nvidia.com/news/test"]


def test_article_missing_container_or_future_publication_is_blocked():
    with pytest.raises(ValueError, match="body_missing"):
        discovery.describe(b"<h1>Title</h1>", URL, datetime.now(UTC))
    with pytest.raises(ValueError, match="future_publication"):
        discovery.describe(ARTICLE, URL, datetime(2026, 1, 1, tzinfo=UTC))


def test_parsed_earnings_stays_candidate_and_does_not_touch_quant(service, monkeypatch):
    body = ARTICLE.replace(
        b"Synthetic announcement",
        b"NVIDIA Announces Financial Results for Second Quarter Fiscal 2027",
    )
    monkeypatch.setattr(
        discovery, "parse_release", lambda *a: {"facts": [{"metric": "revenue", "value": "100"}]}
    )
    result = discovery.describe(body, URL, datetime(2026, 10, 22, tzinfo=UTC))
    assert result["quarter"] == "FY2027-Q2"
    assert result["status"] == "parsed_pending_reconciliation"
    assert result["published_at"] is None
    assert result["available_at"] == "2026-10-22T00:00:00+00:00"
    assert not service.source_db.exists()


def test_only_one_worker_can_own_store_and_lock_is_released_on_shutdown(service, monkeypatch):
    monkeypatch.setattr(product.Product, "_loop", lambda self: self.stop.wait(5))
    service.start()
    other = product.Product(service.source_db, service.raw_dir, service.store.root)
    try:
        with pytest.raises(ValueError, match="已有背景"):
            other.start()
    finally:
        service.close()
    other.start()
    other.close()


def test_manual_refresh_is_deduplicated_and_does_not_call_provider(service, monkeypatch):
    monkeypatch.setattr(product.time, "time", lambda: 100000)
    first = service.update()
    service.update()
    assert first["refresh_queued"] is True
    assert len(service.store.jobs()) == 5
    assert first["operations"]["model_calls"] == 0


def test_product_store_cannot_overlap_source_database_or_raw_directory(tmp_path):
    for root in (tmp_path, tmp_path / "raw" / "nested"):
        with pytest.raises(ValueError, match="分開"):
            product.Product(tmp_path / "formal.db", tmp_path / "raw", root)
