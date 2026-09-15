from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import AvailabilityEvidence, SourceDocument
from valuation_engine.db.store import digest
from valuation_engine.time import ET, aware

VERSION = "availability-1.1"


def add_evidence(
    db: Session,
    source: SourceDocument,
    evidence: SourceDocument,
    published: datetime | None,
    precision: str,
    fallback: datetime,
    scopes: tuple[str, ...] = ("financial_fact", "guidance", "segment"),
) -> None:
    if precision not in ("exact", "minute", "date_only", "inferred_after_close"):
        raise ValueError("Unknown timestamp precision")
    if precision in ("exact", "minute") and published is None:
        raise ValueError("Verified timestamp required")
    if precision in ("exact", "minute"):
        assert published is not None
        available = aware(published) + (
            timedelta(minutes=1) if precision == "minute" else timedelta()
        )
    else:
        available = aware(fallback)
    # A subsequent content revision cannot inherit an earlier publication time.
    if source.metadata_json.get("changed_content"):
        available = max(available, source.retrieved_at)
    reason = (
        None
        if precision == "exact"
        else (
            "Visible timestamp has minute precision; use end of minute"
            if precision == "minute"
            else "No independently verified publication time; next midnight ET is conservative date bound"
        )
    )
    for scope in scopes:
        key = digest([source.id, evidence.id, published, available, precision, scope, VERSION])
        if db.scalar(
            select(AvailabilityEvidence.id).where(AvailabilityEvidence.identity_key == key)
        ):
            continue
        db.add(
            AvailabilityEvidence(
                identity_key=key,
                source_document_id=source.id,
                evidence_document_id=evidence.id,
                scope=scope,
                published_at=published,
                information_available_at=available,
                timestamp_precision=precision,
                timestamp_source=evidence.source_url,
                timestamp_confidence="high" if precision in ("exact", "minute") else "low",
                fallback_reason=reason,
                policy_version=VERSION,
                timezone=str(ET),
            )
        )
    db.flush()


class AvailabilityResolver:
    def __init__(self, db: Session, scope: str = "financial_fact"):
        rows = db.scalars(
            select(AvailabilityEvidence).where(AvailabilityEvidence.scope == scope)
        ).all()
        rank = {"exact": 0, "minute": 1, "date_only": 2, "inferred_after_close": 3}
        self.by_document: dict[int, AvailabilityEvidence] = {}
        for row in sorted(rows, key=lambda x: (rank[x.timestamp_precision], -x.id)):
            self.by_document.setdefault(row.source_document_id, row)

    def time(self, row: Any) -> datetime:
        evidence = self.by_document.get(row.source_document_id)
        return evidence.information_available_at if evidence else row.available_at

    def metadata(self, row: Any) -> dict[str, Any]:
        e = self.by_document.get(row.source_document_id)
        if not e:
            return {
                "information_available_at": row.available_at.isoformat(),
                "timestamp_precision": getattr(row, "metadata_json", {}).get(
                    "timestamp_precision", "unresolved"
                ),
                "timestamp_confidence": getattr(row, "metadata_json", {}).get(
                    "timestamp_confidence", "unknown"
                ),
                "fallback_reason": getattr(row, "metadata_json", {}).get(
                    "fallback_reason", "Legacy source availability retained; no overriding evidence"
                ),
            }
        return {
            "availability_evidence_id": e.id,
            "evidence_document_id": e.evidence_document_id,
            "information_available_at": e.information_available_at.isoformat(),
            "published_at": e.published_at.isoformat() if e.published_at else None,
            "timestamp_precision": e.timestamp_precision,
            "timestamp_source": e.timestamp_source,
            "timestamp_confidence": e.timestamp_confidence,
            "fallback_reason": e.fallback_reason,
            "timezone": e.timezone,
            "policy_version": e.policy_version,
        }
