import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.config import Settings
from valuation_engine.db.schema import Company, DataQualityIssue, FinancialFact, SourceDocument
from valuation_engine.logging import log
from valuation_engine.time import calculate_next_tradable_timestamp, now


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def read_document(
    source: SourceDocument, raw_dir: Path | None = None, *, strict_root=False
) -> bytes:
    """Read immutable evidence; relocated bundles resolve by hash without rewriting provenance."""
    path = Path(source.raw_path)
    if strict_root:
        if raw_dir is None:
            raise ValueError("Explicit raw directory required")
        path = raw_dir / source.content_hash
        if path.is_symlink() or not path.is_file():
            raise ValueError("Isolated source content missing")
    if not path.is_file():
        path = (raw_dir if raw_dir is not None else Settings().qve_raw_dir) / source.content_hash
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != source.content_hash:
        raise ValueError(f"Source document {source.id} hash mismatch")
    return content


def company(db: Session, ticker: str = "NVDA") -> Company:
    if ticker != "NVDA":
        raise ValueError("Milestone 1 supports NVDA only")
    row = db.scalar(select(Company).where(Company.ticker == ticker))
    if row is None:
        row = Company(
            ticker=ticker,
            company_name="NVIDIA Corporation",
            cik="0001045810",
            exchange="NASDAQ",
            currency="USD",
            valuation_archetype="AI Compute / Fabless",
            archetype_confidence=None,
        )
        db.add(row)
        db.flush()
    return row


def issue(
    db: Session,
    kind: str,
    details: dict[str, Any],
    *,
    company_id: int | None = None,
    document_id: int | None = None,
    metric: str | None = None,
    period: str | None = None,
    severity: str = "warning",
) -> None:
    key = digest([kind, details, company_id, document_id, metric, period])
    if db.scalar(select(DataQualityIssue.id).where(DataQualityIssue.identity_key == key)):
        return
    db.add(
        DataQualityIssue(
            identity_key=key,
            company_id=company_id,
            source_document_id=document_id,
            issue_type=kind,
            severity=severity,
            metric_name=metric,
            fiscal_period=period,
            details=details,
        )
    )
    db.flush()
    log("validation_warning", issue_type=kind, metric=metric, period=period, details=details)


def document(
    db: Session,
    raw_dir: Path,
    content: bytes,
    *,
    url: str,
    company_id: int,
    provider: str,
    kind: str,
    published_at: datetime | None,
    filing_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> SourceDocument:
    sha = hashlib.sha256(content).hexdigest()
    existing = db.scalar(
        select(SourceDocument).where(
            SourceDocument.source_url == url, SourceDocument.content_hash == sha
        )
    )
    if existing:
        return existing
    previous = db.scalar(select(SourceDocument.id).where(SourceDocument.source_url == url))
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / sha
    path.write_bytes(content)
    meta = dict(metadata or {})
    if previous:
        meta["changed_content"] = True
    row = SourceDocument(
        company_id=company_id,
        filing_id=filing_id,
        source_url=url,
        document_type=kind,
        published_at=published_at,
        retrieved_at=now(),
        content_hash=sha,
        source_provider=provider,
        raw_path=str(path.resolve()),
        metadata_json=meta,
    )
    db.add(row)
    db.flush()
    return row


def add_fact(db: Session, **data: Any) -> tuple[FinancialFact, bool]:
    # Source document + semantic context + value retains conflicts instead of overwriting.
    key = digest(
        {
            k: data[k]
            for k in (
                "source_document_id",
                "metric_name",
                "taxonomy_name",
                "value",
                "unit",
                "period_start",
                "period_end",
                "duration_kind",
            )
        }
    )
    row = db.scalar(select(FinancialFact).where(FinancialFact.identity_key == key))
    if row:
        return row, False
    previous = db.scalars(
        select(FinancialFact).where(
            FinancialFact.company_id == data["company_id"],
            FinancialFact.metric_name == data["metric_name"],
            FinancialFact.period_end == data["period_end"],
            FinancialFact.period_start == data["period_start"],
            FinancialFact.duration_kind == data["duration_kind"],
            FinancialFact.unit == data["unit"],
        )
    ).all()
    changed = [x for x in previous if x.value != data["value"]]
    data["is_restated"] = any(x.available_at < data["available_at"] for x in changed)
    if changed:
        issue(
            db,
            "source_disagreement",
            {
                "prior_fact_ids": [x.id for x in changed],
                "new_value": str(data["value"]),
                "note": "Revision candidate, not proof of accounting restatement; inspect split basis and source.",
            },
            company_id=data["company_id"],
            document_id=data["source_document_id"],
            metric=data["metric_name"],
        )
    row = FinancialFact(
        identity_key=key,
        tradable_at=calculate_next_tradable_timestamp(data["available_at"]),
        **data,
    )
    db.add(row)
    db.flush()
    return row, True
