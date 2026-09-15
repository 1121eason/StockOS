import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import (
    DataQualityIssue,
    FinancialFact,
    QualityReview,
    SourceDocument,
)
from valuation_engine.db.store import digest
from valuation_engine.hardening.availability import AvailabilityResolver
from valuation_engine.hardening.guidance import guidance_coverage
from valuation_engine.normalization.quarterly import PointInTimeRepository


def review_quality(
    db: Session,
    company_id: int,
    as_of: datetime,
    *,
    snapshot_fact_ids: dict[str, list[int]] | None = None,
) -> list[dict[str, Any]]:
    repo = PointInTimeRepository(db, company_id)
    resolver = AvailabilityResolver(db)
    coverage = guidance_coverage(db, company_id)
    rows = []
    for issue in db.scalars(select(DataQualityIssue).order_by(DataQualityIssue.id)):
        category = "Source Limitation"
        blocking = True
        resolution = "open"
        evidence: dict[str, Any] = {
            "original_issue_type": issue.issue_type,
            "original_details": issue.details,
        }
        if issue.issue_type == "publication_time_missing":
            category = "Timestamp Gap"
            source_id = issue.source_document_id
            e = resolver.by_document.get(source_id) if source_id else None
            if e and e.timestamp_precision in ("minute", "exact"):
                blocking = False
                resolution = "resolved_with_evidence"
                evidence["availability_evidence_id"] = e.id
        elif issue.issue_type == "missing_metric":
            match = re.fullmatch(r"FY(\d+)-Q(\d)", issue.fiscal_period or "")
            q = repo.quarter(int(match[1]), int(match[2]), as_of) if match else None
            obs = q.metrics.get(issue.metric_name) if q and issue.metric_name else None
            if issue.metric_name == "period_end_shares" and q and "revenue" in q.metrics:
                from valuation_engine.hardening.shares import get_latest_known_shares
                from valuation_engine.time import calculate_next_tradable_timestamp

                trade = calculate_next_tradable_timestamp(q.metrics["revenue"].available_at)
                shares = get_latest_known_shares(db, company_id, trade)
                evidence["valuation_timestamp"] = trade.isoformat()
                evidence["share_observation_id"] = shares["observation_id"] if shares else None
                evidence["policy"] = (
                    "PM accepts latest previously known eligible shares; exact new quarter-end shares are not required"
                )
                if shares:
                    blocking = False
                    resolution = "resolved_via_pit_shares"
            elif obs:
                category = "Parser Defect"
                blocking = False
                resolution = "resolved_with_evidence"
                evidence["observation"] = obs.model_dump(mode="json")
            elif issue.metric_name in (
                "cash",
                "marketable_securities",
                "debt_current",
                "debt_noncurrent",
                "debt",
            ):
                blocking = False
                resolution = "conditional_metric_gap_retained"
                evidence["impact"] = (
                    "PM permits explicitly incomplete EV when balances are unavailable; no zero filling or unverified substitution"
                )
            else:
                evidence["impact"] = (
                    "Unavailable for this metric; never filled with weighted-average shares or assumed zero"
                )
        elif issue.issue_type == "guidance_unparsed":
            category = "Parser Defect"
            found = [r for r in coverage if r["quarter"] == issue.fiscal_period]
            if len(found) == 4 and all(r["status"] == "structured" for r in found):
                blocking = False
                resolution = "resolved_with_evidence"
                evidence["guidance_ids"] = [i for r in found for i in r["guidance_item_ids"]]
        elif issue.issue_type == "fcf_definition_difference":
            category = "Definition Difference"
            blocking = False
            resolution = "documented"
            evidence["policy"] = (
                "Engine FCF is OCF minus reported capex; issuer FCF additionally subtracts equipment principal payments. Both retained. Not an accounting restatement."
            )
        elif issue.issue_type == "source_disagreement":
            category = "Reconciliation Conflict"
            resolution = "review_reconciliation_results"
            if snapshot_fact_ids:
                candidates = set(
                    db.scalars(
                        select(FinancialFact.id).where(
                            FinancialFact.company_id == company_id,
                            FinancialFact.source_document_id == issue.source_document_id,
                            FinancialFact.metric_name == issue.metric_name,
                            FinancialFact.value == Decimal(issue.details["new_value"]),
                        )
                    )
                )
                affected = {
                    quarter: sorted(candidates.intersection(ids))
                    for quarter, ids in snapshot_fact_ids.items()
                    if candidates.intersection(ids)
                }
                evidence["candidate_fact_ids"] = sorted(candidates)
                evidence["reviewed_snapshot_quarters"] = sorted(snapshot_fact_ids)
                evidence["affected_snapshot_fact_ids"] = affected
                if candidates and not affected:
                    blocking = False
                    resolution = "unresolved_but_excluded_from_reviewed_snapshots"
                    evidence["impact"] = (
                        "Source discrepancy remains unresolved and both versions are retained. "
                        "The differing later candidates occur in none of the listed financial "
                        "snapshots or valuation inputs. This is a scoped impact finding, "
                        "not a general approval of the conflicting facts or a verified restatement."
                    )
        elif issue.issue_type in (
            "non_fiscal_period_end",
            "unsupported_duration",
            "unmapped_period",
        ):
            category = "Expected Missing"
            blocking = False
            resolution = "excluded_context"
        elif issue.issue_type in ("historical_forecast_missing", "ttm_window_incomplete"):
            category = "Expected Missing"
            blocking = False
            resolution = "documented"
        elif issue.issue_type == "price_reconstructed_only":
            blocking = False
            resolution = "accepted_by_PM_for_research_backtest"
            evidence["impact"] = (
                "PM accepts verified research_reconstructed prices; an independent raw-price vendor is not required for M1.1"
            )
        elif issue.issue_type == "ingestion_failure":
            evidence["impact"] = "Actual source ingestion evidence is still required"
            if issue.details.get("provider") == "SEC":
                count = db.scalar(
                    select(func.count(FinancialFact.id))
                    .join(SourceDocument)
                    .where(
                        FinancialFact.company_id == company_id,
                        SourceDocument.source_provider == "SEC",
                    )
                )
                evidence["actual_sec_fact_count"] = count
                if count:
                    blocking = False
                    resolution = "resolved_with_actual_sec_ingestion"
                    evidence["impact"] = (
                        "Original ingestion failure retained; subsequent SEC facts now exist. "
                        "Target primary-document coverage and live idempotency are assessed separately."
                    )
        row = {
            "issue_id": issue.id,
            "classification": category,
            "blocking": blocking,
            "resolution": resolution,
            "evidence": evidence,
        }
        key = digest([row, "quality-review-1.1"])
        if not db.scalar(select(QualityReview.id).where(QualityReview.identity_key == key)):
            db.add(QualityReview(identity_key=key, **row))
        rows.append(row)
    db.flush()
    return rows
