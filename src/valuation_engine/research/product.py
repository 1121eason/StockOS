"""NVDA local shadow operation: independent quotes, official sources and research.

Only the isolated product store is writable. New parsed releases require
reconciliation before they can enter a new Quant valuation. No model calls.
"""

import copy
import fcntl
import hashlib
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from valuation_engine.research import discovery, financial_refresh
from valuation_engine.research.market_quote import compare_price, fetch_quote
from valuation_engine.research.product_store import ProductStore, digest
from valuation_engine.research.workbench import build_research

VERSION = "NVDAProductRefreshV2"
INTERVALS = {
    "COLLECT_QUOTES": 300,
    "DISCOVER_SOURCES": 3600,
    "VERIFY_RESEARCH": 21600,
    "REFRESH_FINANCIALS": 3600,
}
LABELS = {
    "COLLECT_QUOTES": "股價更新",
    "DISCOVER_SOURCES": "官方公告檢查",
    "INGEST_DOCUMENT": "公告保存與解析",
    "VERIFY_RESEARCH": "既有研究核對",
    "REFRESH_FINANCIALS": "新財報核對與研究重建",
}


class Product:
    def __init__(self, source_db: Path, raw_dir: Path, store: Path, *, deployment: str = "local"):
        if deployment not in ("local", "cloud"):
            raise ValueError("unsupported_deployment")
        self.deployment = deployment
        self.source_db, self.raw_dir = source_db.resolve(), raw_dir.resolve()
        root = store.resolve()
        if (
            root == self.source_db.parent
            or self.source_db.is_relative_to(root)
            or self.raw_dir.is_relative_to(root)
            or root.is_relative_to(self.raw_dir)
        ):
            raise ValueError("產品儲存區必須與正式來源分開。")
        self.store = ProductStore(root)
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.lease: TextIO | None = None
        self.last_attempt = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        lease = (self.store.root / "worker.lock").open("a+")
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lease.close()
            raise ValueError("此產品儲存區已有背景更新程序。") from None
        self.lease = lease
        self.store.recover(time.time())
        self.stop.clear()
        self.thread = threading.Thread(target=self._loop, name="StockOS-NVDA-worker", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=20)
            if self.thread.is_alive():
                # Keep lock until owned thread exits; never permit a concurrent worker.
                return
        self._release()

    def _release(self):
        if self.lease is not None:
            self.lease.close()
            self.lease = None

    def _loop(self):
        try:
            while not self.stop.is_set():
                try:
                    self.tick()
                except Exception as exc:
                    self.store.observe("worker_error", {"type": type(exc).__name__}, time.time())
                self.stop.wait(1)
        finally:
            self.store.observe("worker", {"status": "stopped"}, time.time())
            self._release()

    def schedule(self, at: float):
        for kind, interval in INTERVALS.items():
            self.store.enqueue(kind, f"{VERSION}:{kind}:{int(at // interval)}", {}, at)

    def tick(self, now: float | None = None):
        at = time.time() if now is None else now
        self.store.observe("worker", {"status": "running"}, at)
        self.schedule(at)
        job = self.store.claim(at)
        if job is None:
            return None
        try:
            result = self.execute(job, at)
            finished = time.time() if now is None else now
            self.store.finish(job, finished, result)
            self.store.observe("success:" + job["kind"], {"job_id": job["id"]}, finished)
        except Exception as exc:
            # Logs expose error class only: no credentials, arbitrary source text or paths.
            error = (
                exc.code
                if isinstance(exc, financial_refresh.RefreshBlocked)
                else type(exc).__name__
            )
            if job["kind"] == "REFRESH_FINANCIALS" and not isinstance(
                exc, financial_refresh.RefreshBlocked
            ):
                self.store.observe(
                    "financial_refresh",
                    {
                        "status": "blocked",
                        "code": "unexpected_failure",
                        "reason": "財報更新未完成，保留上一份正常研究；請查看更新紀錄。",
                    },
                    time.time(),
                )
            self.store.finish(job, time.time() if now is None else now, error=error)
        return job["id"]

    def _archive(self, raw: bytes) -> str:
        identity = hashlib.sha256(raw).hexdigest()
        folder = self.store.root / "raw"
        folder.mkdir(exist_ok=True)
        path = folder / identity
        if path.exists():
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != identity:
                raise ValueError("archived_source_hash_mismatch")
        else:
            temp = folder / (identity + ".tmp")
            with temp.open("wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            directory = os.open(folder, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        return identity

    def execute(self, job: dict, at: float):
        kind, payload = job["kind"], job["payload"]
        if kind == "VERIFY_RESEARCH":
            previous = self.store.latest("research")
            if previous and previous["payload"].get("database_ref"):
                financial_refresh.verify_publication(self.store.root, previous["payload"])
                return previous["id"]
            result = build_research(self.source_db, self.raw_dir)
            # Identical research does not become a new publication every refresh.
            identity = digest({k: v for k, v in result.items() if k != "verified_at"})
            previous = self.store.latest("research")
            if previous and previous["identity"] == identity:
                return previous["id"]
            published = self.store.publish(
                "research",
                identity,
                result,
                at,
                pointer="research",
                message="已保存核對後的季度研究；AI 與未來目標價仍待驗收。",
            )
            self.store.enqueue("COLLECT_QUOTES", "quote-for-research:" + published, {}, at)
            return published
        if kind == "REFRESH_FINANCIALS":
            releases = [
                r["payload"]
                for r in self.store.current("source_document", limit=200)
                if r["payload"].get("status") == "parsed_pending_reconciliation"
            ]
            if not releases:
                return None
            article = max(releases, key=lambda r: (r["quarter"], r["received_at"]))
            previous = self.store.latest("research")
            saved = previous["payload"] if previous else None
            if saved and article["quarter"] < saved["current"]["quarter"]:
                return previous["id"]
            try:
                result = financial_refresh.rebuild(
                    self.source_db, self.raw_dir, self.store.root, article, saved
                )
            except financial_refresh.RefreshBlocked as exc:
                self.store.observe(
                    "financial_refresh",
                    {
                        "status": "blocked",
                        "quarter": article["quarter"],
                        "reason": financial_refresh.REASONS[exc.code],
                        "code": exc.code,
                    },
                    time.time(),
                )
                raise
            if result is None:
                self.store.observe(
                    "financial_refresh",
                    {
                        "status": "unchanged_verified",
                        "quarter": article["quarter"],
                        "source_hash": article["source_hash"],
                        "reason": "已核對最新公告，本季財務與假設未改變。",
                    },
                    time.time(),
                )
                return previous["id"] if previous else None
            published = self.store.publish(
                "research",
                digest(result),
                result,
                time.time(),
                pointer="research",
                message=article["quarter"] + " 財務已核對，預測與估值已重新計算；AI 仍待驗收。",
            )
            self.store.observe(
                "financial_refresh",
                {
                    "status": "rebuilt",
                    "quarter": article["quarter"],
                    "source_hash": article["source_hash"],
                    "research_id": published,
                    "reason": None,
                },
                time.time(),
            )
            self.store.enqueue("COLLECT_QUOTES", "quote-for-research:" + published, {}, time.time())
            return published
        if kind == "COLLECT_QUOTES":
            research = self.store.latest("research")
            basis = datetime.fromtimestamp(at, UTC).date().isoformat()
            if research:
                c = research["payload"]["current"]
                basis = c["valuation"].get("basis_date", c["checkpoint"][:10])
            quote = fetch_quote(basis)
            self.store.observe("quote_attempt", quote, at)
            if quote["status"] == "unavailable":
                raise ValueError("quote_unavailable")
            return self.store.publish("quote", digest(quote), quote, at, pointer="quote")
        if kind == "DISCOVER_SOURCES":
            # Each index is its own job so one failed source does not hide another.
            for url in discovery.INDEXES:
                self.store.enqueue("READ_INDEX", f"index:{url}:{int(at // 3600)}", {"url": url}, at)
            return None
        if kind == "READ_INDEX":
            raw = discovery.download(payload["url"], index=True)
            identity = self._archive(raw)
            links = discovery.discover(raw)
            for url in links:
                self.store.enqueue(
                    "INGEST_DOCUMENT",
                    f"document:{url}:{int(at // 3600)}",
                    {"url": url, "index_hash": identity},
                    at,
                )
            return self.store.publish(
                "source_index",
                identity,
                {"url": payload["url"], "source_hash": identity, "links": links},
                at,
            )
        if kind == "INGEST_DOCUMENT":
            raw = discovery.download(payload["url"])
            at = max(at, time.time())
            source_hash = self._archive(raw)
            pointer = "source:" + payload["url"]
            previous = self.store.latest(pointer)
            if previous and previous["payload"]["source_hash"] == source_hash:
                return previous["id"]
            article = discovery.describe(raw, payload["url"], datetime.fromtimestamp(at, UTC))
            article["discovered_from_hash"] = payload["index_hash"]
            article["supersedes"] = previous["id"] if previous else None
            published = self.store.publish(
                "source_document",
                source_hash,
                article,
                at,
                pointer=pointer,
                message="官方公告更新：" + article["title"],
                alert_key="event:" + article["event_fingerprint"],
            )
            if article["status"] == "parsed_pending_reconciliation":
                self.store.enqueue(
                    "REFRESH_FINANCIALS",
                    f"financial:{article['event_fingerprint']}:{int(at // 3600)}",
                    {},
                    at,
                )
            return published
        raise ValueError("unsupported_product_job")

    def update(self):
        at = time.time()
        self.schedule(at)
        for kind in ("COLLECT_QUOTES", "VERIFY_RESEARCH", "REFRESH_FINANCIALS"):
            self.store.enqueue(kind, f"manual:{kind}:{int(at // 30)}", {}, at)
        for url in discovery.INDEXES:
            self.store.enqueue(
                "READ_INDEX", f"manual-index:{url}:{int(at // 30)}", {"url": url}, at
            )
        result = self.load()
        result["refresh_queued"] = True
        return result

    def health(self):
        at = time.time()
        worker = self.store.observation("worker")
        verification = self.store.observation("success:VERIFY_RESEARCH")
        running = bool(worker and worker["value"]["status"] == "running" and at - worker["at"] < 90)
        jobs = self.store.jobs()
        reasons = {
            "COLLECT_QUOTES": "行情或拆股資料暫時無法核對，保留上次報價。",
            "VERIFY_RESEARCH": "既有研究來源或計算核對未通過，保留上一版。",
            "READ_INDEX": "官方公告列表暫時無法讀取或格式改變。",
            "INGEST_DOCUMENT": "原始公告讀取、格式或保存未通過。",
        }
        return {
            "version": VERSION,
            "mode": "financial_refresh",
            "deployment": self.deployment,
            "research_verified_at": datetime.fromtimestamp(verification["at"], UTC).isoformat()
            if verification
            else None,
            "worker_running": running,
            "heartbeat_at": datetime.fromtimestamp(worker["at"], UTC).isoformat()
            if worker
            else None,
            "intervals_seconds": INTERVALS,
            "jobs": [
                {
                    **j,
                    "label": LABELS.get(j["kind"], "來源列表讀取"),
                    "reason": (
                        financial_refresh.REASONS.get(j["error"])
                        or reasons.get(j["kind"], "研究重建未完成，保留上一版；請查看更新狀態。")
                    )
                    if j["error"]
                    else None,
                }
                for j in jobs
            ],
            "ai_status": "pending_acceptance",
            "financial_refresh": self.store.observation("financial_refresh"),
            "model_calls": 0,
            "formal_database_writes": 0,
            "notification_channel": "in_app",
            "coverage": "NVIDIA 官方公告與本季 SEC 財務核對；尚未涵蓋所有法說 Q&A 與外部產業線索",
        }

    def load(self):
        research = self.store.latest("research")
        quotes = self.store.latest("quote")
        health = self.health()
        sources = self.store.current("source_document")
        # One current version per URL; history is retained separately.
        current_sources: dict[str, Any] = {}
        for row in sources:
            current_sources.setdefault(row["payload"]["url"], row)
        events = [
            {"id": row["id"], **{k: v for k, v in row["payload"].items() if k != "financials"}}
            for row in current_sources.values()
        ]
        if research:
            applied = research["payload"].get("financial_refresh", {}).get("source_hash")
            refresh = (self.store.observation("financial_refresh") or {}).get("value", {})
            for event in events:
                if event.get("source_hash") == applied:
                    event.update(
                        status="research_rebuilt",
                        model_impact="本季財務已核對，預測與估值已重建並保存。",
                    )
                elif refresh.get("status") == "unchanged_verified" and event.get(
                    "source_hash"
                ) == refresh.get("source_hash"):
                    event.update(
                        status="research_unchanged_verified", model_impact=refresh["reason"]
                    )
        quote = (
            copy.deepcopy(quotes["payload"]) if quotes else {"status": "unavailable", "price": None}
        )
        attempt = self.store.observation("quote_attempt")
        if quotes and (
            time.time() - quotes["created"] > INTERVALS["COLLECT_QUOTES"] * 2
            or (attempt and attempt["value"]["status"] == "unavailable")
        ):
            quote.update(status="stale", reason="報價更新未完成，顯示上次可用報價")
        target = {
            "status": "unavailable",
            "target_at": None,
            "horizon": "12_months_proposed",
            "base": None,
            "bull": None,
            "bear": None,
            "stress": None,
            "reason": "12 個月目標價尚缺已驗收的時間推導方法；研究日合理價值另列。",
        }
        result = {
            "snapshot_id": research["id"] if research else None,
            "research": None,
            "last_attempt": None,
            "operations": health,
            "events": events,
            "alerts": self.store.alerts(),
            "target_valuation": target,
            "publication_status": "Partial" if research else "Updating",
            "message": "背景正在更新股價、檢查官方財報；財務核對通過後會重建預測與估值。",
        }
        if not health["worker_running"]:
            result["publication_status"] = "Stale" if research else "Blocked"
        if research:
            data = copy.deepcopy(research["payload"])
            comparison = {"status": "unavailable", "gap": None, "reason": "報價與估值基準尚未對齊"}
            basis = data["current"]["valuation"].get(
                "basis_date", data["current"]["checkpoint"][:10]
            )
            if quote.get("valuation_basis_date") == basis:
                comparison = compare_price(data["current"]["valuation"], quote)
            # Existing verified research stays intact; quote channel is explicit and separate.
            data.update(quote=quote, price_comparison=comparison)
            result["research"] = data
            cutoff = datetime.fromisoformat(data["current"]["checkpoint"])
            if time.time() - cutoff.timestamp() > 120 * 86400:
                result["publication_status"] = "Stale"
        result["quote"] = quote
        return result
