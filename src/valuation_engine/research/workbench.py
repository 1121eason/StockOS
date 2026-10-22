"""NVDA-only, verified read adapter and atomic local research publication.

Does not replay/mutate formal Quant, Regime or AI tables. Market quotes never
enter forecasts, DCF inputs or AI context. Raw paths stored in the DB are ignored.
"""

import hashlib
import json
import os
import re
import sqlite3
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from valuation_engine.cadence.formal_context import load_formal_context
from valuation_engine.cadence.revision_context import load_revision_context
from valuation_engine.db.schema import (
    AvailabilityEvidence,
    Company,
    FinancialFact,
    QuarterlySnapshot,
    SourceDocument,
)
from valuation_engine.normalization.quarterly import PointInTimeRepository, prior_period
from valuation_engine.regime.features import eligible_runs
from valuation_engine.research.dcf import DCFModel
from valuation_engine.research.market_quote import compare_price, fetch_quote
from valuation_engine.research.numbers import POLICY, MarketEquityShares, canonical
from valuation_engine.time import aware

METRICS = ("revenue", "operating_income", "net_income", "eps_diluted", "ocf", "capex", "fcf")
VERSION = "NVDAWorkbenchV1"


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_preflight(path: Path) -> str:
    if not path.is_file() or any(
        Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")
    ):
        raise ValueError("來源資料庫不存在或有未結清 sidecar，請先提供一致的研究資料庫。")
    return file_hash(path)


def readonly_engine(path: Path):
    def connect():
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        conn.execute("PRAGMA query_only=ON")
        return conn

    return create_engine("sqlite://", creator=connect)


def _ids(value: Any) -> set[int]:
    found: set[int] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("source_document_id", "evidence_document_id") and type(item) is int:
                found.add(item)
            found.update(_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_ids(item))
    return found


def verified_sources(db: Session, ids: set[int], raw_dir: Path) -> list[dict]:
    sources = []
    for source_id in sorted(ids):
        doc = db.get(SourceDocument, source_id)
        if doc is None or not re.fullmatch(r"[0-9a-f]{64}", doc.content_hash):
            raise ValueError("來源身分或內容雜湊無效。")
        raw = raw_dir / doc.content_hash
        if not raw.is_file() or raw.is_symlink() or file_hash(raw) != doc.content_hash:
            raise ValueError(f"來源文件 {source_id} 的原始內容缺失或雜湊不符。")
        host = urlsplit(doc.source_url).hostname
        official = host in ("nvidianews.nvidia.com", "www.sec.gov", "sec.gov", "data.sec.gov")
        time_records = list(
            db.scalars(
                select(AvailabilityEvidence)
                .where(AvailabilityEvidence.source_document_id == source_id)
                .order_by(AvailabilityEvidence.id)
            )
        )
        sources.append(
            {
                "id": doc.id,
                "url": doc.source_url,
                "sha256": doc.content_hash,
                "provider": doc.source_provider,
                "official_disclosure": official,
                "retrieved_at": doc.retrieved_at,
                "published_at": doc.published_at,
                "availability_records": [
                    {
                        "id": row.id,
                        "scope": row.scope,
                        "published_at": row.published_at,
                        "available_at": row.information_available_at,
                        "precision": row.timestamp_precision,
                        "source_url": row.timestamp_source,
                        "evidence_document_id": row.evidence_document_id,
                    }
                    for row in time_records
                ],
                "verification": "cached_bytes_sha256_match",
            }
        )
    return sources


def reconcile_valuation(metadata: dict, stored: Any) -> dict:
    projection, source = metadata["dcf_projection"], metadata["source_valuation"]
    if stored is None or projection["status"] != "available":
        return {
            "status": "unavailable",
            "base": None,
            "reason": projection.get("reason", "估值輸入不足"),
            "missing": metadata.get("missing", []),
        }
    balance, shares = source["inputs"], source.get("shares")
    if not shares or any("balance:" + k not in balance for k in ("cash", "debt")):
        return {"status": "unavailable", "base": None, "reason": "缺少現金、負債或 PIT 股數"}
    flows = [Decimal(v) for v in projection["cashflows"]]
    cash, debt = (Decimal(balance["balance:" + k]["value"]) for k in ("cash", "debt"))
    count = MarketEquityShares(Decimal(shares["share_count"]))
    scenarios = []
    for saved in metadata["sensitivity"]:
        if saved["status"] != "available":
            continue
        calculated = canonical(
            DCFModel().value(
                flows, cash, debt, count, Decimal(saved["wacc"]), Decimal(saved["terminal_growth"])
            )
        )
        if calculated["status"] != "available" or calculated["per_share"] != saved["per_share"]:
            raise ValueError("敏感度重算與已保存的正式結果不一致，停止發布。")
        scenarios.append(calculated)
    base = next(
        (
            s
            for s in scenarios
            if Decimal(s["wacc"]) == Decimal(POLICY["wacc_base"])
            and Decimal(s["terminal_growth"]) == Decimal(POLICY["terminal_growth_base"])
        ),
        None,
    )
    if base is None or Decimal(base["per_share"]) != Decimal(str(stored)):
        raise ValueError("基準估值重算與已保存的正式結果不一致，停止發布。")
    return {
        "status": "available",
        "base": base["per_share"],
        "low": min(Decimal(s["per_share"]) for s in scenarios),
        "high": max(Decimal(s["per_share"]) for s in scenarios),
        "scenarios": scenarios,
        "wacc": POLICY["wacc_base"],
        "terminal_growth": POLICY["terminal_growth_base"],
        "basis_date": source["basis_date"],
        "shares": shares,
        "cash": cash,
        "debt": debt,
        "cashflows": flows,
        "balance_lineage": {key: balance["balance:" + key] for key in ("cash", "debt")},
        "formula": projection["formula"],
        "limitations": projection["limitations"],
        "verification": "all_saved_scenarios_recomputed_with_unchanged_DCFPolicyV1",
    }


def quarter_data(db: Session, path: Path, run) -> tuple[dict, set[int], Any]:
    quarter = run.metadata_json["anchor"]
    formal = load_formal_context(
        path, "NVDA", quarter, run.forecast_as_of.date().isoformat(), run.forecast_as_of
    )
    return quarter_values(db, run, formal)


def quarter_values(db: Session, run, formal) -> tuple[dict, set[int], Any]:
    """Verify a selected cohort's financial values using the unchanged normalizer."""
    quarter = run.metadata_json["anchor"]
    valuation_metadata = json.loads(formal.metadata_json)
    snapshot = db.get(QuarterlySnapshot, run.input_snapshot_id)
    if snapshot is None or snapshot.company_id != run.company_id:
        raise ValueError("季度財務快照身分不符。")
    if quarter != f"FY{snapshot.fiscal_year}-Q{snapshot.fiscal_quarter}":
        raise ValueError("季度與財務快照不一致。")
    reconstructed = PointInTimeRepository(db, run.company_id).quarter(
        snapshot.fiscal_year, snapshot.fiscal_quarter, run.information_cutoff
    )
    if reconstructed is None:
        raise ValueError("無法從既有財務來源重建季度。")
    ids = _ids(run.metadata_json["provenance"]) | _ids(valuation_metadata["source_valuation"])
    metrics: dict[str, Any] = {}
    for name in METRICS:
        observation = snapshot.payload["metrics"].get(name)
        if observation is None:
            metrics[name] = {"value": None, "reason": "此季度缺少已核對的資料", "source_ids": []}
            continue
        if aware(datetime.fromisoformat(observation["available_at"])) > run.information_cutoff:
            raise ValueError("財務數字晚於研究截止時間。")
        normalized = reconstructed.metrics.get(name)
        if (
            normalized is None
            or Decimal(observation["value"]) != normalized.value
            or observation["fact_ids"] != list(normalized.fact_ids)
        ):
            raise ValueError("財務快照與既有標準化來源不一致，停止發布。")
        metric_ids = set()
        for fact_id in observation["fact_ids"]:
            fact = db.get(FinancialFact, fact_id)
            if fact is None or fact.company_id != run.company_id:
                raise ValueError("財務數字來源身分不符。")
            metric_ids.add(fact.source_document_id)
        ids.update(metric_ids)
        ids.update(_ids(observation))
        metrics[name] = {**observation, "source_ids": sorted(metric_ids)}
    return (
        {
            "quarter": quarter,
            "forecast_run_id": run.id,
            "valuation_id": formal.valuation_id,
            "financial_snapshot_id": snapshot.id,
            "checkpoint": run.forecast_as_of,
            "information_cutoff": run.information_cutoff,
            "period_end": snapshot.payload["period_end"],
            "metrics": metrics,
            "regime": formal.regime,
            "valuation": reconcile_valuation(valuation_metadata, formal.dcf_base),
            "forecast_model": run.model_version,
            "valuation_model": POLICY["valuation_version"],
            "assumption_set_id": run.assumption_set_id,
            "classification": run.generated_kind,
        },
        ids,
        formal,
    )


def build_research(path: Path, raw_dir: Path) -> dict:
    before = source_preflight(path)
    engine = readonly_engine(path)
    try:
        with Session(engine, autoflush=False) as db:
            company = db.scalar(select(Company).where(Company.ticker == "NVDA"))
            if company is None:
                raise ValueError("找不到 NVDA 正式研究資料。")
            runs = eligible_runs(db, company.id, datetime.now(UTC))
            if len(runs) < 2:
                raise ValueError("需要連續兩季的正式研究成果。")
            previous_run, current_run = runs[-2:]
            current, current_ids, formal = quarter_data(db, path, current_run)
            previous, previous_ids, _ = quarter_data(db, path, previous_run)
            match = re.fullmatch(r"FY(\d+)-Q(\d)", current["quarter"])
            if match is None:
                raise ValueError("研究季度格式無效。")
            fy, fq = prior_period(*map(int, match.groups()))
            if previous["quarter"] != f"FY{fy}-Q{fq}":
                raise ValueError("上一季研究不連續，不可替代為其他季度。")
            revisions = []
            fiscal_year = int(current["quarter"][2:6])
            for target in (f"FY{fiscal_year}", f"FY{fiscal_year + 1}"):
                receipt = load_revision_context(path, formal, target).receipt
                if receipt.get("previous_run_id") not in (None, previous_run.id):
                    raise ValueError("預測修訂沒有對齊畫面上的上一季。")
                revisions.append(receipt)
            sources = verified_sources(db, current_ids | previous_ids, raw_dir)
            result = canonical(
                {
                    "version": VERSION,
                    "ticker": "NVDA",
                    "name": "NVIDIA",
                    "currency": "USD",
                    "current": current,
                    "previous": previous,
                    "revisions": revisions,
                    "sources": sources,
                    "source_database_sha256": before,
                    "verified_at": datetime.now(UTC),
                    "historical_oos": False,
                    "ai": {
                        "status": "pending_acceptance",
                        "affects_valuation": False,
                        "analysis": None,
                        "reason": "尚無適用本研究版本的正式核准 AI 分析",
                    },
                }
            )
    finally:
        engine.dispose()
    if source_preflight(path) != before:
        raise ValueError("讀取期間來源資料庫改變，保留上一份正常結果。")
    return result


class Workbench:
    def __init__(self, source_db: Path, raw_dir: Path, store: Path):
        self.source_db, self.raw_dir, self.store = (
            source_db.resolve(),
            raw_dir.resolve(),
            store.resolve(),
        )
        if (
            self.source_db.is_relative_to(self.store)
            or self.raw_dir.is_relative_to(self.store)
            or self.store.is_relative_to(self.raw_dir)
        ):
            raise ValueError("工作台儲存區必須與正式來源分開。")
        self.lock = threading.Lock()
        self.last_attempt: dict[str, Any] | None = None

    def load(self) -> dict:
        pointer = json.loads((self.store / "current.json").read_text())
        identity = pointer["snapshot_id"]
        if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
            raise ValueError("研究快照指標無效。")
        path = self.store / (identity + ".json")
        if file_hash(path) != identity:
            raise ValueError("研究快照雜湊不符。")
        return {
            "snapshot_id": identity,
            "research": json.loads(path.read_text()),
            "last_attempt": self.last_attempt,
        }

    def update(self) -> dict:
        if not self.lock.acquire(blocking=False):
            raise ValueError("另一個更新正在執行，請稍後。")
        try:
            result = build_research(self.source_db, self.raw_dir)
            quote = fetch_quote(
                result["current"]["valuation"].get(
                    "basis_date", result["current"]["checkpoint"][:10]
                )
            )
            result.update(
                quote=quote, price_comparison=compare_price(result["current"]["valuation"], quote)
            )
            content = json.dumps(
                result, ensure_ascii=False, sort_keys=True, allow_nan=False
            ).encode()
            identity = hashlib.sha256(content).hexdigest()
            self.store.mkdir(parents=True, exist_ok=True)
            snapshot = self.store / (identity + ".json")
            if snapshot.exists():
                if snapshot.is_symlink() or file_hash(snapshot) != identity:
                    raise ValueError("同名研究快照內容不符，停止發布。")
            else:
                with snapshot.open("xb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            pointer = self.store / ".current.tmp"
            with pointer.open("w") as stream:
                json.dump({"snapshot_id": identity}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(pointer, self.store / "current.json")
            self.last_attempt = {"status": "success", "at": datetime.now(UTC).isoformat()}
            return self.load()
        except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, SQLAlchemyError) as exc:
            self.last_attempt = {
                "status": "failed",
                "at": datetime.now(UTC).isoformat(),
                "reason": str(exc)
                if isinstance(exc, ValueError)
                else "來源讀取或保存失敗，上一份正常研究保持不變。",
            }
            raise ValueError(self.last_attempt["reason"]) from exc
        finally:
            self.lock.release()
