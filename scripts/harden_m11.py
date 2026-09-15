"""Replay M1.1 evidence and produce reproducible acceptance reports. No network calls."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from valuation_engine.cli.main import migrate
from valuation_engine.config import Settings
from valuation_engine.db.schema import (
    Base,
    Filing,
    FinancialFact,
    SourceDocument,
)
from valuation_engine.db.session import engine
from valuation_engine.db.store import issue, read_document
from valuation_engine.features.engine import compute, persist
from valuation_engine.hardening.availability import AvailabilityResolver
from valuation_engine.hardening.basis import SplitBasis, build_price_bases, get_price_as_reported
from valuation_engine.hardening.guidance import guidance_coverage
from valuation_engine.hardening.ingest import (
    add_date_fallbacks,
    import_timestamp_evidence,
    ingest_splits,
)
from valuation_engine.hardening.quality import review_quality
from valuation_engine.hardening.reconcile import CANONICAL_RULE, reconcile
from valuation_engine.hardening.valuation import historical_value_at
from valuation_engine.ingestion.ir import replay_ir_cache
from valuation_engine.normalization.quarterly import PointInTimeRepository
from valuation_engine.time import ET, calculate_next_tradable_timestamp


def run(settings: Settings, out: Path):
    out.mkdir(parents=True, exist_ok=True)

    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2, default=str, sort_keys=True) + "\n")

    migrate(settings)
    with Session(engine(settings.qve_database_url)) as db:
        ir = replay_ir_cache(db, settings, Path("data/ir-manifest.json"))
        timestamps = import_timestamp_evidence(
            db, settings, Path("data/m11/timestamps-manifest.json")
        )
        add_date_fallbacks(db)
        splits = ingest_splits(db, settings, Path("data/m11/splits-manifest.json"))
        from valuation_engine.hardening.price_archive import import_price_archive

        archive = None
        if Path("data/m11/price-manifest.json").exists():
            archive = import_price_archive(db, settings, Path("data/m11/price-manifest.json"))
        prices = build_price_bases(db, 1, archive)
        reconciliations = reconcile(db, 1)
        resolver = AvailabilityResolver(db)
        repo = PointInTimeRepository(db, 1)
        split = SplitBasis(db, 1)
        quotes = []
        gate = []
        timestamp_rows = []
        consistency = []
        for doc in db.scalars(
            select(SourceDocument)
            .where(SourceDocument.source_provider == "NVIDIA IR")
            .order_by(SourceDocument.id)
        ):
            fy, fq = doc.metadata_json["fiscal_year"], doc.metadata_json["fiscal_quarter"]
            e = resolver.by_document[doc.id]
            pub = e.published_at
            available = e.information_available_at
            opening = calculate_next_tradable_timestamp(available)
            q = repo.quarter(fy, fq, opening)
            assert q is not None
            snapshot = repo.save(q)
            persist(db, snapshot, compute(repo, q))
            value = historical_value_at(db, repo, q, opening)
            quote = get_price_as_reported(db, 1, opening)
            row = {
                "quarter": f"FY{fy}-Q{fq}",
                "as_of": opening.isoformat(),
                "snapshot_id": snapshot.id,
                "valuation_id": value.id,
                **{
                    m: str(getattr(value, m)) if getattr(value, m) is not None else None
                    for m in (
                        "market_price",
                        "trailing_pe",
                        "market_cap",
                        "enterprise_value",
                        "fcf_yield",
                    )
                },
                "provenance": value.metadata_json,
            }
            quotes.append(row)
            filing = db.scalar(
                select(Filing)
                .where(
                    Filing.company_id == 1,
                    Filing.fiscal_year == fy,
                    Filing.fiscal_quarter == fq,
                    Filing.form_type.in_(("10-Q", "10-K")),
                )
                .order_by(Filing.filing_date, Filing.accepted_timestamp)
            )
            timestamp_rows.append(
                {
                    "quarter": row["quarter"],
                    "published_at": pub.astimezone(ET).isoformat() if pub else None,
                    "information_available_at": available.astimezone(ET).isoformat(),
                    "tradable_at": opening.isoformat(),
                    "timestamp_precision": e.timestamp_precision,
                    "timestamp_confidence": e.timestamp_confidence,
                    "fallback_reason": e.fallback_reason,
                    "source": e.timestamp_source,
                    "evidence_document_id": e.evidence_document_id,
                    "ir_own_publication_timestamp": None,
                    "ir_own_precision": "date_only",
                    "sec_accepted_timestamp": filing.accepted_timestamp.astimezone(ET).isoformat()
                    if filing and filing.accepted_timestamp
                    else None,
                    "sec_filing_date": str(filing.filing_date) if filing else None,
                    "sec_filing_timestamp_precision": "date_only" if filing else "unresolved",
                    "note": "Earliest verified issuer-distributed financial content; IR website time not falsely inferred from distribution; SEC pending ingestion",
                }
            )
            eps = q.metrics.get("eps_diluted")
            shares = q.metrics.get("diluted_shares")
            basis = eps.metadata.get("share_basis_date") if eps else None
            from datetime import date

            factor = split.factor(date.fromisoformat(basis), opening.date()) if basis else None
            rounding_tolerance = (
                (
                    shares.value * Decimal(".005")
                    + abs(eps.value) * Decimal("500000")
                    + Decimal("500000")
                )
                if eps and shares
                else None
            )
            net_income = q.value("net_income")
            accounting_delta = (
                abs(eps.value * shares.value - net_income)
                if eps and shares and net_income is not None
                else None
            )
            accounting_ok = (
                accounting_delta is not None
                and rounding_tolerance is not None
                and accounting_delta <= rounding_tolerance
            )
            consistency.append(
                {
                    "quarter": row["quarter"],
                    "eps": str(eps.value) if eps else None,
                    "diluted_weighted_shares": str(shares.value) if shares else None,
                    "share_basis_date": basis,
                    "period_end_shares": str(q.value("period_end_shares"))
                    if q.value("period_end_shares")
                    else None,
                    "to_trading_date_factor": str(factor),
                    "price": quote,
                    "eps_times_diluted_shares": str(eps.value * shares.value)
                    if eps and shares
                    else None,
                    "reported_net_income": str(q.value("net_income")),
                    "status": "PASS"
                    if eps
                    and shares
                    and basis
                    and quote
                    and quote["available_at"] == opening
                    and accounting_ok
                    else "FAIL",
                    "accounting_delta": str(accounting_delta),
                    "rounding_tolerance": str(rounding_tolerance),
                    "eps_shares_net_income_consistent": accounting_ok,
                    "rounding_note": "EPS reported to cents; EPS * rounded weighted shares need not exactly equal net income",
                }
            )
            if (fy, fq) in ((2022, 1), (2024, 1), (2027, 2)):
                before = repo.quarter(fy, fq, pub - timedelta(microseconds=1)) if pub else None
                after = repo.quarter(fy, fq, available + timedelta(microseconds=1))
                checks = {
                    "before_release_invisible": pub is not None and before is None,
                    "after_available_visible": after is not None
                    and after.value("revenue") is not None,
                    "price_is_first_open": quote is not None and quote["available_at"] == opening,
                    "trailing_pe_available": value.trailing_pe is not None,
                    "market_cap_available": value.market_cap is not None,
                    "full_provenance": bool(value.metadata_json.get("inputs")) and bool(quote),
                }
                gate.append(
                    {
                        **row,
                        "before_cutoff": pub - timedelta(microseconds=1) if pub else None,
                        "after_cutoff": available + timedelta(microseconds=1),
                        "checks": checks,
                        "status": "PASS" if all(checks.values()) else "FAIL",
                    }
                )
        issue(
            db,
            "price_reconstructed_only",
            {
                "provider": "Yahoo Chart",
                "rows": 1682,
                "impact": "Raw as-traded OHLC reconstructed from verified split factors; no independent raw-price provider observation",
            },
            company_id=1,
        )
        issue(
            db,
            "historical_forecast_missing",
            {
                "impact": "No valid annual historically observed forward estimate; forward PE intentionally null"
            },
            company_id=1,
        )
        for early in quotes:
            if early["quarter"] in ("FY2021-Q1", "FY2021-Q2", "FY2021-Q3"):
                issue(
                    db,
                    "ttm_window_incomplete",
                    {"impact": "Four-quarter TTM requires periods before the target dataset start"},
                    company_id=1,
                    period=early["quarter"],
                )
        coverage = guidance_coverage(db, 1)
        issues = review_quality(db, 1, datetime(2026, 9, 12, tzinfo=ET))
        counts = {
            t.name: db.scalar(select(func.count()).select_from(t))
            for t in Base.metadata.sorted_tables
        }
        sec = {
            "filings": counts["filings"],
            "facts": db.scalar(
                select(func.count())
                .select_from(FinancialFact)
                .join(SourceDocument)
                .where(SourceDocument.source_provider == "SEC")
            ),
            "unique_accessions": db.scalar(
                select(func.count(func.distinct(Filing.accession_number)))
            ),
            "status": "blocked_missing_SEC_USER_AGENT" if not counts["filings"] else "ingested",
            "canonical_rule": CANONICAL_RULE,
            "reconciliation_counts": reconciliations,
            "actual_idempotency": "not_run"
            if not counts["filings"]
            else "requires_actual_second_ingestion",
        }
        audit = []
        for doc in db.scalars(select(SourceDocument)):
            audit.append(
                {
                    "document_id": doc.id,
                    "hash_verified": hashlib.sha256(
                        read_document(doc, settings.qve_raw_dir)
                    ).hexdigest()
                    == doc.content_hash,
                }
            )
        db.commit()
        for name, value in [
            ("timestamp-coverage.json", timestamp_rows),
            ("timestamp-verification.json", timestamps),
            ("guidance-coverage.json", coverage),
            ("quarterly-basis-validation.json", consistency),
            ("historical-valuations.json", quotes),
            ("pm-gate.json", gate),
            ("quality-review.json", issues),
            ("sec-coverage.json", sec),
            ("counts.json", counts),
            ("source-integrity.json", audit),
        ]:
            save(name, value)
        result = {
            "ir": ir,
            "splits": splits,
            "price_bases": prices,
            "timestamps": dict(Counter(r["timestamp_precision"] for r in timestamp_rows)),
            "guidance": dict(Counter(r["status"] for r in coverage)),
            "valuations": {
                m: sum(r[m] is not None for r in quotes)
                for m in ("trailing_pe", "market_cap", "enterprise_value", "fcf_yield")
            },
            "gate": [
                {"quarter": r["quarter"], "status": r["status"], "checks": r["checks"]}
                for r in gate
            ],
            "quality": {
                "total": len(issues),
                "blocking": sum(r["blocking"] for r in issues),
                "classification": dict(Counter(r["classification"] for r in issues)),
                "m1_original_142": {
                    "reviewed": sum(r["issue_id"] <= 142 for r in issues),
                    "blocking": sum(r["blocking"] for r in issues if r["issue_id"] <= 142),
                }
                if db.get_bind().dialect.name == "sqlite"
                else {
                    "note": "Fresh PostgreSQL workflow; original M1 review is in the SQLite report"
                },
            },
            "all_source_hashes_verified": all(r["hash_verified"] for r in audit),
            "counts": counts,
        }
        save("summary.json", result)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/m11/report")
    args = parser.parse_args()
    print(json.dumps(run(Settings(), Path(args.output)), indent=2, default=str))
