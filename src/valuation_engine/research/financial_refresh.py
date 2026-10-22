"""NVDA-only financial refresh in an isolated, immutable product database.

The seed is read-only. A failed download, reconciliation or calculation cannot
move the publication pointer. All model policies are shared with the existing
research engine; quotes and AI are deliberately absent from this module.
"""

import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from valuation_engine.config import Settings
from valuation_engine.db.schema import (
    AssumptionSet,
    AvailabilityEvidence,
    Company,
    Filing,
    FinancialFact,
    ForecastRun,
    RegimeSnapshot,
    ResearchValuation,
    SourceDocument,
)
from valuation_engine.db.store import digest
from valuation_engine.hardening.availability import AvailabilityResolver
from valuation_engine.ingestion.http import SourceClient
from valuation_engine.ingestion.ir import ingest_release, parse_release
from valuation_engine.ingestion.sec import ingest_sec
from valuation_engine.normalization.quarterly import PointInTimeRepository, prior_period
from valuation_engine.regime.confidence import POLICY as REGIME_POLICY
from valuation_engine.regime.confidence import snapshot_contract
from valuation_engine.regime.service import payload as regime_policy_payload
from valuation_engine.regime.service import replay_runs
from valuation_engine.research.discovery import official_url
from valuation_engine.research.inputs import FinancialInputs, period_name, period_tuple
from valuation_engine.research.numbers import canonical
from valuation_engine.research.service import (
    MODELS,
    build_forecast,
    compare_forecasts,
    policy_payload,
)
from valuation_engine.research.valuation import build_live_valuation
from valuation_engine.research.workbench import (
    file_hash,
    quarter_data,
    quarter_values,
    readonly_engine,
    source_preflight,
    verified_sources,
)

VERSION = "NVDAFinancialRefreshV1"
REQUIRED = {"revenue", "operating_income", "net_income", "ocf", "capex"}
SEC_URLS = (
    "https://data.sec.gov/submissions/CIK0001045810.json",
    "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json",
)
REASONS = {
    "sec_identity_missing": "缺少 SEC 下載聯絡設定，保留上一份研究。",
    "sec_unavailable": "SEC 資料尚未取得，稍後重新檢查。",
    "financials_incomplete": "本季財務資料不完整，尚未更新估值。",
    "sec_reconciliation_pending": "等待本季 SEC 財報完成數字核對。",
    "financial_conflict": "公司公告與 SEC 數字不一致，需人工核對。",
    "quarter_gap": "缺少連續上一季的研究，尚未發布新結果。",
    "source_revision_requires_review": "同一季的財務數字有修改，需人工核對後再更新。",
    "source_integrity": "原始資料或研究檔案核對未通過，保留上一份研究。",
}


class RefreshBlocked(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def identity(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RefreshBlocked("source_integrity")
    return value


def database_path(root: Path, value: str) -> Path:
    path = root / "research" / (identity(value) + ".sqlite")
    if path.parent.is_symlink() or path.is_symlink() or source_preflight(path) != value:
        raise RefreshBlocked("source_integrity")
    return path


class SecSnapshot(SourceClient):
    """Two bounded HTTPS requests, then a fully offline existing SEC parser."""

    def __init__(self, user_agent):
        self.responses = {}
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            for url in SEC_URLS:
                with client.stream("GET", url, headers={"User-Agent": user_agent}) as response:
                    response.raise_for_status()
                    parts, size = [], 0
                    for part in response.iter_bytes():
                        size += len(part)
                        if size > 30_000_000:
                            raise RefreshBlocked("sec_unavailable")
                        parts.append(part)
                    raw = b"".join(parts)
                    value = json.loads(raw)
                    if str(value.get("cik", "")).lstrip("0") != "1045810":
                        raise RefreshBlocked("sec_unavailable")
                    self.responses[url] = raw
        self.observed_at = datetime.now(UTC)

    def get(self, url):
        if url not in self.responses:
            raise RefreshBlocked("sec_unavailable")
        return self.responses[url]


def cohort(db, company_id, cutoff):
    rows = db.scalars(
        select(ForecastRun)
        .join(AssumptionSet)
        .where(
            ForecastRun.company_id == company_id,
            ForecastRun.forecast_type.in_(("first_tradable", "live")),
            ForecastRun.model_name == MODELS["A"],
            ForecastRun.forecast_as_of <= cutoff,
            ForecastRun.information_cutoff <= cutoff,
            AssumptionSet.content_hash == digest(policy_payload()),
        )
        .order_by(ForecastRun.forecast_as_of, ForecastRun.id)
    )
    latest = {}
    for row in rows:
        latest[row.metadata_json["anchor"]] = row
    return latest


def reconcile_release(db, co, doc, parsed, cutoff):
    """Only current-period, original SEC filings can confirm this release.

    Per-share basis is verified separately by the existing normalizer. No later
    comparative or amended filing is used to approve an original announcement.
    """
    resolver = AvailabilityResolver(db)
    ir = list(db.scalars(select(FinancialFact).where(FinancialFact.source_document_id == doc.id)))
    sec = list(
        db.scalars(
            select(FinancialFact)
            .join(Filing, FinancialFact.filing_id == Filing.id)
            .where(
                FinancialFact.company_id == co.id,
                Filing.period_end <= parsed["end"],
                Filing.is_amendment.is_(False),
                Filing.form_type.in_(("10-Q", "10-K")),
            )
        )
    )
    if not REQUIRED.issubset({f.metric_name for f in ir}):
        raise RefreshBlocked("financials_incomplete")
    sec_ids = {f.source_document_id for f in sec}
    # SEC reports cash flow cumulatively. Reuse the existing quarter normalizer
    # (including its YTD subtraction and same-accession preference), restricted
    # to SEC sources, rather than comparing six months with three months.
    normalized = PointInTimeRepository(db, co.id, source_document_ids=sec_ids).quarter(
        doc.metadata_json["fiscal_year"], doc.metadata_json["fiscal_quarter"], cutoff
    )
    confirmations, missing = [], []
    for left in ir:
        if left.metric_name not in REQUIRED:
            continue
        if left.duration_kind == "quarter":
            observation = normalized.metrics.get(left.metric_name) if normalized else None
            if observation is None:
                missing.append(left.metric_name)
                continue
            if observation.value != left.value or observation.unit != left.unit:
                raise RefreshBlocked("financial_conflict")
            confirmations.append(
                {
                    "metric": left.metric_name,
                    "ir_fact_id": left.id,
                    "sec_fact_ids": list(observation.fact_ids),
                    "formula": observation.formula,
                    "status": "match",
                }
            )
            continue
        candidates = [
            right
            for right in sec
            if (
                (right.metric_name, right.period_start, right.period_end, right.duration_kind)
                == (left.metric_name, left.period_start, left.period_end, left.duration_kind)
                and resolver.time(right) <= cutoff
            )
        ]
        if not candidates:
            missing.append(left.metric_name)
            continue
        rank = min(f.source_priority for f in candidates)
        candidates = [f for f in candidates if f.source_priority == rank]
        if any(f.value != left.value or f.unit != left.unit for f in candidates):
            raise RefreshBlocked("financial_conflict")
        confirmations.append(
            {
                "metric": left.metric_name,
                "ir_fact_id": left.id,
                "sec_fact_ids": [f.id for f in candidates],
                "status": "match",
            }
        )
    if missing:
        raise RefreshBlocked("sec_reconciliation_pending")
    return {
        "status": "matched",
        "comparisons": confirmations,
        "source_document_ids": sorted(
            {
                doc.id,
                *(
                    db.get(FinancialFact, fact_id).source_document_id
                    for item in confirmations
                    for fact_id in item["sec_fact_ids"]
                ),
            }
        ),
    }


def observe_release(db, doc, received):
    # A previously verified capture retains its historical evidence. A newly
    # imported capture receives observed-now evidence, never a backdated release.
    if not doc.metadata_json.get("product_observed_at"):
        return
    received = max(received, datetime.fromisoformat(doc.metadata_json["product_observed_at"]))
    for scope in ("financial_fact", "guidance", "segment"):
        key = digest([doc.id, received, scope, VERSION])
        if db.scalar(
            select(AvailabilityEvidence.id).where(AvailabilityEvidence.identity_key == key)
        ):
            continue
        db.add(
            AvailabilityEvidence(
                identity_key=key,
                source_document_id=doc.id,
                evidence_document_id=doc.id,
                scope=scope,
                published_at=None,
                information_available_at=received,
                timestamp_precision="date_only",
                timestamp_source=doc.source_url,
                timestamp_confidence="low",
                fallback_reason="Publication time unverified; eligibility starts at this product's actual capture, not historical publication day",
                policy_version=VERSION,
                timezone="UTC",
            )
        )
    db.flush()


def _copy_sources(db, roots, destination):
    if destination.is_symlink():
        raise RefreshBlocked("source_integrity")
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for doc in db.scalars(select(SourceDocument)):
        name = identity(doc.content_hash)
        target = destination / name
        candidates = [target, *(root / name for root in roots)]
        source = next((p for p in candidates if p.is_file()), None)
        if source is not None:
            if source.is_symlink() or file_hash(source) != name:
                raise RefreshBlocked("source_integrity")
            if source != target:
                shutil.copyfile(source, target)
            copied.append(name)
        # Preserve immutable source records. The product session binds reads to
        # this directory instead of changing the original provenance paths.
    return sorted(set(copied))


def _quarter(db, path, run):
    if run.forecast_type == "first_tradable":
        return quarter_data(db, path, run)
    valuations = list(
        db.scalars(select(ResearchValuation).where(ResearchValuation.forecast_run_id == run.id))
    )
    regimes = list(
        db.scalars(
            select(RegimeSnapshot).where(
                RegimeSnapshot.forecast_run_id == run.id,
                RegimeSnapshot.policy_version == REGIME_POLICY["version"],
            )
        )
    )
    if len(valuations) != 1 or len(regimes) != 1:
        raise RefreshBlocked("source_integrity")
    value, regime = valuations[0], regimes[0]
    if (
        value.as_of_timestamp != run.forecast_as_of
        or value.metadata_json["forecast_key"] != run.identity_key
        or regime.input_snapshot_id != run.input_snapshot_id
        or regime.metadata_json["assumption_hash"] != digest(regime_policy_payload(REGIME_POLICY))
    ):
        raise RefreshBlocked("source_integrity")
    envelope = snapshot_contract(regime)
    envelope.update(
        company_id=run.company_id,
        input_snapshot_id=run.input_snapshot_id,
        checkpoint_timestamp=run.forecast_as_of.isoformat(),
        input_lineage=regime.metadata_json["inputs"],
        stress_dimensions=regime.metadata_json["state"]["stress_dimensions"],
    )
    context = SimpleNamespace(
        valuation_id=value.id,
        dcf_base=value.dcf_base,
        metadata_json=json.dumps(value.metadata_json),
        regime=envelope,
    )
    result, ids, _ = quarter_values(db, run, context)
    result["classification"] = "live_observed_research_not_investment_approved"
    return result, ids, context


def _revision_receipts(comparison, run, previous):
    result = []
    fy, _ = period_tuple(run.metadata_json["anchor"])
    for year in (fy, fy + 1):
        target = f"FY{year}"
        item = next((r for r in comparison["comparisons"] if r["target"] == target), None)
        metrics = (
            {
                k: item["metrics"][k]["percentage_revision"]
                for k in ("revenue", "eps", "free_cash_flow")
            }
            if item
            else None
        )
        result.append(
            {
                "target": target,
                "forecast_run_id": run.id,
                "previous_run_id": previous.id,
                "metrics": metrics,
                "status": "AVAILABLE"
                if metrics and all(v is not None for v in metrics.values())
                else "INCOMPLETE",
                "reason": None if metrics else "selected_fiscal_target_not_available",
                "previous_label": item["previous_label"] if item else None,
                "new_label": item["new_label"] if item else None,
                "split_factor": comparison["split_factor"],
            }
        )
    return result


def rebuild(seed: Path, seed_raw: Path, root: Path, article: dict, previous_payload=None):
    """Return a fully verified candidate; caller alone atomically publishes it."""
    url = official_url(article["url"])
    raw = root / "raw" / identity(article["source_hash"])
    if raw.is_symlink() or file_hash(raw) != article["source_hash"]:
        raise RefreshBlocked("source_integrity")
    fy, fq = period_tuple(article["quarter"])
    parsed = parse_release(raw.read_bytes(), fy, fq)
    fingerprint = digest(canonical(parsed))
    if previous_payload and previous_payload.get("database_ref"):
        verify_publication(root, previous_payload)
    if (
        previous_payload
        and previous_payload.get("financial_refresh", {}).get("financial_fingerprint")
        == fingerprint
    ):
        return None
    if (
        previous_payload
        and previous_payload.get("database_ref")
        and previous_payload["current"]["quarter"] == article["quarter"]
    ):
        raise RefreshBlocked("source_revision_requires_review")
    baseline = (
        database_path(root, previous_payload["database_ref"])
        if previous_payload and previous_payload.get("database_ref")
        else seed
    )
    before = source_preflight(baseline)
    received = datetime.fromisoformat(article["received_at"])
    if received.tzinfo is None or received > datetime.now(UTC):
        raise RefreshBlocked("source_integrity")
    with tempfile.TemporaryDirectory(prefix="financial-refresh-", dir=root) as folder:
        candidate = Path(folder) / "candidate.sqlite"
        shutil.copyfile(baseline, candidate)
        if source_preflight(candidate) != before:
            raise RefreshBlocked("source_integrity")
        engine = create_engine("sqlite:///" + str(candidate))
        try:
            with Session(engine) as db:
                db.info["research_raw_dir"] = root / "raw"
                co = db.scalar(select(Company).where(Company.ticker == "NVDA"))
                if co is None or str(co.cik).lstrip("0") != "1045810":
                    raise RefreshBlocked("source_integrity")
                _copy_sources(db, [seed_raw], root / "raw")
                settings = Settings(_env_file=None, qve_raw_dir=root / "raw")  # type: ignore[call-arg]
                ingest_release(db, settings, raw.read_bytes(), url, fy, fq, observed_at=received)
                doc = db.scalar(
                    select(SourceDocument).where(
                        SourceDocument.source_url == url,
                        SourceDocument.content_hash == article["source_hash"],
                    )
                )
                if doc is None:
                    raise RefreshBlocked("source_integrity")
                observe_release(db, doc, received)
                try:
                    reconciliation = reconcile_release(db, co, doc, parsed, datetime.now(UTC))
                except RefreshBlocked as error:
                    if error.code != "sec_reconciliation_pending":
                        raise
                    try:
                        agent = settings.require_sec_identity()
                    except ValueError:
                        raise RefreshBlocked("sec_identity_missing") from None
                    try:
                        client = SecSnapshot(agent)
                        ingest_sec(
                            db,
                            settings,
                            client,
                            download_filings=False,
                            period_end=parsed["end"],
                            observed_at=client.observed_at,
                        )
                    except (httpx.HTTPError, ValueError, KeyError):
                        raise RefreshBlocked("sec_unavailable") from None
                    db.flush()
                    reconciliation = reconcile_release(db, co, doc, parsed, datetime.now(UTC))
                cutoff = datetime.now(UTC)
                runs = cohort(db, co.id, cutoff)
                prior_key = period_name(*prior_period(fy, fq))
                previous = runs.get(prior_key)
                if previous is None or any(period_tuple(k) > (fy, fq) for k in runs):
                    raise RefreshBlocked("quarter_gap")
                data = FinancialInputs(db, co.id, cutoff)
                if data.anchor != (fy, fq):
                    raise RefreshBlocked("source_integrity")
                for fact in db.scalars(
                    select(FinancialFact).where(FinancialFact.source_document_id == doc.id)
                ):
                    if fact.metric_name in REQUIRED and fact.duration_kind == "quarter":
                        obs = data.current.metrics.get(fact.metric_name)
                        if obs is None or obs.value != fact.value:
                            raise RefreshBlocked("source_revision_requires_review")
                run = build_forecast(db, co.id, cutoff, checkpoint="live", model="A", data=data)
                build_live_valuation(db, run)
                history = [r for k, r in sorted(runs.items()) if period_tuple(k) < (fy, fq)]
                replay_runs(db, co.id, [*history, run], REGIME_POLICY, allow_live=True)
                comparison = compare_forecasts(db, run, previous)
                raw_hashes = _copy_sources(db, [seed_raw], root / "raw")
                run_id, previous_id = run.id, previous.id
                db.commit()
        finally:
            engine.dispose()
        # Read back the committed file, then independently recompute displayed
        # metrics and every DCF scenario before installing the immutable artifact.
        engine = readonly_engine(candidate)
        try:
            with Session(engine, autoflush=False) as db:
                run, previous = db.get(ForecastRun, run_id), db.get(ForecastRun, previous_id)
                current, ids, _ = _quarter(db, candidate, run)
                prior, old_ids, _ = _quarter(db, candidate, previous)
                ids |= old_ids | set(reconciliation["source_document_ids"])
                for source in list(
                    db.scalars(select(SourceDocument).where(SourceDocument.id.in_(ids)))
                ):
                    api_id = source.metadata_json.get("api_source_document_id")
                    if api_id:
                        ids.add(api_id)
                sources = verified_sources(db, ids, root / "raw")
                result = canonical(
                    {
                        "version": VERSION,
                        "ticker": "NVDA",
                        "name": "NVIDIA",
                        "currency": "USD",
                        "current": current,
                        "previous": prior,
                        "revisions": _revision_receipts(comparison, run, previous),
                        "sources": sources,
                        "database_source_hashes": raw_hashes,
                        "verified_at": datetime.now(UTC),
                        "historical_oos": False,
                        "ai": {
                            "status": "pending_acceptance",
                            "affects_valuation": False,
                            "analysis": None,
                            "reason": "本季 AI 尚未完成真人驗收",
                        },
                        "financial_refresh": {
                            "version": VERSION,
                            "status": "rebuilt",
                            "financial_fingerprint": fingerprint,
                            "observed_at": received,
                            "computed_at": cutoff,
                            "source_hash": article["source_hash"],
                            "reconciliation": reconciliation,
                            "formal_database_writes": 0,
                            "quote_inputs": False,
                            "ai_inputs": False,
                        },
                    }
                )
        finally:
            engine.dispose()
        if source_preflight(baseline) != before:
            raise RefreshBlocked("source_integrity")
        key = source_preflight(candidate)
        destination = root / "research" / (key + ".sqlite")
        destination.parent.mkdir(exist_ok=True)
        with candidate.open("rb") as stream:
            os.fsync(stream.fileno())
        if destination.exists():
            database_path(root, key)
        else:
            os.replace(candidate, destination)
        # Make source bytes and the immutable DB durable before publishing a
        # pointer in the separate operations store.
        for name in raw_hashes:
            with (root / "raw" / name).open("rb") as stream:
                os.fsync(stream.fileno())
        for durable_directory in (root / "raw", destination.parent):
            descriptor = os.open(durable_directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        result.update(database_ref=key, source_database_sha256=key)
        return result


def verify_publication(root: Path, saved: dict):
    path = database_path(root, saved["database_ref"])
    engine = readonly_engine(path)
    try:
        with Session(engine, autoflush=False) as db:
            for key in ("current", "previous"):
                run = db.get(ForecastRun, saved[key]["forecast_run_id"])
                result, _, _ = _quarter(db, path, run)
                if canonical(result) != saved[key]:
                    raise RefreshBlocked("source_integrity")
            verified_sources(db, {s["id"] for s in saved["sources"]}, root / "raw")
    finally:
        engine.dispose()
    return saved
