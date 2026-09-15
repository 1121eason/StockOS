"""Run the accepted M1.1 closure policy; live SEC requires explicit --live-sec and identity."""

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from valuation_engine.cli.main import migrate
from valuation_engine.config import Settings
from valuation_engine.db.schema import (
    Base,
    Filing,
    FinancialFact,
    GuidanceItem,
    SourceDocument,
)
from valuation_engine.db.session import engine
from valuation_engine.db.store import read_document
from valuation_engine.hardening.availability import AvailabilityResolver
from valuation_engine.hardening.guidance import current_guidance_ids
from valuation_engine.hardening.quality import review_quality
from valuation_engine.hardening.reconcile import reconciliation_report
from valuation_engine.hardening.shares import (
    filing_availability,
    get_latest_known_shares,
    ingest_cover_shares,
)
from valuation_engine.hardening.valuation import historical_value_at
from valuation_engine.ingestion.sec import ingest_sec
from valuation_engine.normalization.quarterly import PointInTimeRepository
from valuation_engine.time import calculate_next_tradable_timestamp, now

ROOT = Path(__file__).resolve().parents[1]
REPS = {(2022, 1), (2024, 1), (2027, 2)}


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str, sort_keys=True) + "\n")


def run(settings, out, live_sec=False):
    migrate(settings)
    live_path = out / "live-sec.json"
    if live_sec:
        settings.require_sec_identity()  # Validate without printing the contact.
        results = []
        for iteration in (1, 2):
            try:
                with Session(engine(settings.qve_database_url)) as db:
                    result = ingest_sec(db, settings)
                    db.commit()
                results.append({"run": iteration, **result})
                save(live_path, {"status": "executed", "runs": results})
            except Exception as exc:
                save(
                    live_path,
                    {
                        "status": "failed",
                        "runs": results,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                break  # Preserve the failure receipt and still regenerate truthful partial coverage.
    try:
        settings.require_sec_identity()
        identity_ready = True
    except ValueError:
        identity_ready = False
    live = (
        json.loads(live_path.read_text())
        if live_path.exists()
        else {
            "status": "not_executed",
            "reason": "SEC_USER_AGENT not yet configured; live calls await user identity"
            if not identity_ready
            else "No live execution requested for this report directory; this is a local/cache workflow",
            "runs": [],
        }
    )
    with Session(engine(settings.qve_database_url)) as db:
        covers = ingest_cover_shares(db, 1)
        reconciliation = reconciliation_report(db, 1)
        repo = PointInTimeRepository(db, 1)
        resolver = AvailabilityResolver(db)
        guidance_resolver = AvailabilityResolver(db, "guidance")
        guidance_ids = current_guidance_ids(db, 1)
        guidance_rows = list(db.scalars(select(GuidanceItem).where(GuidanceItem.company_id == 1)))
        quarters, gates = [], []
        for doc in db.scalars(
            select(SourceDocument)
            .where(SourceDocument.source_provider == "NVIDIA IR")
            .order_by(SourceDocument.id)
        ):
            fy, fq = doc.metadata_json["fiscal_year"], doc.metadata_json["fiscal_quarter"]
            if fy < 2021 or (fy, fq) > (2027, 2):
                continue
            evidence = resolver.by_document[doc.id]
            boundary = evidence.information_available_at
            trade = calculate_next_tradable_timestamp(boundary)
            before = repo.quarter(fy, fq, boundary - timedelta(microseconds=1))
            after = repo.quarter(fy, fq, boundary + timedelta(microseconds=1))
            q = repo.quarter(fy, fq, trade)
            assert q is not None
            snapshot = repo.save(q)
            value = historical_value_at(db, repo, q, trade)
            shares = get_latest_known_shares(db, 1, trade)
            guidance = [
                {
                    "id": g.id,
                    "source_document_id": g.source_document_id,
                    "metric": g.metric_name,
                    "for_period": g.guidance_for_period,
                    "value": g.mid_value,
                    "available_at": guidance_resolver.time(g),
                }
                for g in guidance_rows
                if g.id in guidance_ids
                and g.source_document_id == doc.id
                and guidance_resolver.time(g) <= trade
            ]
            metadata = value.metadata_json
            row = {
                "quarter": f"FY{fy}-Q{fq}",
                "information_available_at": boundary,
                "valuation_at": trade,
                "financial_snapshot_id": snapshot.id,
                "financial_and_valuation_fact_ids": sorted(
                    {i for o in q.metrics.values() for i in o.fact_ids}
                    | {i for o in metadata["inputs"].values() for i in o["fact_ids"]}
                ),
                "valuation_id": value.id,
                "shares": shares,
                "guidance": guidance,
                **{
                    metric: getattr(value, metric)
                    for metric in (
                        "market_price",
                        "market_cap",
                        "enterprise_value",
                        "fcf_yield",
                        "trailing_pe",
                    )
                },
                "eps_ttm_normalized": metadata["eps_ttm_normalized"],
                "fcf_ttm": metadata["fcf_ttm"],
                "ev_completeness": metadata["ev_completeness"],
                "ev_missing_components": metadata["ev_missing_components"],
                "provenance": metadata,
            }
            quarters.append(row)
            if (fy, fq) not in REPS:
                continue
            filing = db.scalar(
                select(Filing)
                .where(
                    Filing.company_id == 1,
                    Filing.period_end == q.period_end,
                    Filing.form_type.in_(("10-Q", "10-K")),
                )
                .order_by(Filing.filing_date, Filing.id)
            )
            sec_stage = {"status": "unavailable", "reason": "No actual target-period SEC filing"}
            sec_check = False
            if filing:
                accepted, sec_available, policy = filing_availability(filing)
                sec_facts = list(
                    db.scalars(
                        select(FinancialFact).where(
                            FinancialFact.filing_id == filing.id,
                            FinancialFact.fiscal_year == fy,
                            FinancialFact.fiscal_quarter == fq,
                        )
                    )
                )
                ir_facts = list(
                    db.scalars(
                        select(FinancialFact).where(FinancialFact.source_document_id == doc.id)
                    )
                )

                def context(f):
                    return (f.metric_name, f.period_start, f.period_end, f.duration_kind, f.unit)

                ir_contexts = {context(f) for f in ir_facts}
                only = [f for f in sec_facts if context(f) not in ir_contexts]
                primary = db.scalar(
                    select(SourceDocument).where(
                        SourceDocument.filing_id == filing.id,
                        SourceDocument.document_type == "SEC primary filing",
                    )
                )
                eligible = [f.id for f in only if resolver.time(f) <= sec_available]
                premature = [f.id for f in only if resolver.time(f) < sec_available]
                before_sec = repo.quarter(fy, fq, sec_available - timedelta(microseconds=1))
                after_sec = repo.quarter(fy, fq, sec_available)
                before_ids = (
                    {i for o in before_sec.metrics.values() for i in o.fact_ids}
                    if before_sec
                    else set()
                )
                after_ids = (
                    {i for o in after_sec.metrics.values() for i in o.fact_ids}
                    if after_sec
                    else set()
                )
                premature_selected = before_ids.intersection(eligible)
                post_inputs_public = after_sec is not None and all(
                    o.available_at <= sec_available for o in after_sec.metrics.values()
                )
                sec_check = bool(
                    primary
                    and sec_facts
                    and only
                    and eligible
                    and not premature
                    and not premature_selected
                    and post_inputs_public
                )
                sec_stage = {
                    "status": "PASS" if sec_check else "FAIL",
                    "filing_id": filing.id,
                    "accession": filing.accession_number,
                    "accepted_at": accepted,
                    "information_available_at": sec_available,
                    "policy": policy,
                    "primary_document_id": primary.id if primary else None,
                    "sec_only_fact_ids": [f.id for f in only],
                    "eligible_after_boundary": eligible,
                    "premature_fact_ids": premature,
                    "canonical_fact_ids_before_sec": sorted(before_ids),
                    "canonical_fact_ids_after_sec": sorted(after_ids),
                    "premature_selected_sec_fact_ids": sorted(premature_selected),
                    "post_sec_canonical_inputs_public": post_inputs_public,
                    "canonical_note": "Eligible SEC facts need not replace earlier IR facts for the same metric",
                }
            checks = {
                "before_issuer_boundary_unavailable": before is None,
                "after_issuer_boundary_visible": after is not None,
                "after_issuer_only_public_inputs": bool(after)
                and all(
                    o.available_at <= boundary + timedelta(microseconds=1)
                    for o in after.metrics.values()
                ),
                "sec_only_disclosures_obey_boundary": sec_check,
                "first_permitted_price": metadata["price"] is not None
                and datetime.fromisoformat(metadata["price"]["available_at"]) == trade,
                "guidance_available_at_trade": bool(guidance)
                and all(g["available_at"] <= trade for g in guidance),
                "shares_available_at_trade": shares is not None and shares["available_at"] <= trade,
                "trailing_pe_available": value.trailing_pe is not None,
                "market_cap_available": value.market_cap is not None,
                "ev_correctly_complete_or_missing": (value.enterprise_value is not None)
                == (not metadata["ev_missing_components"]),
                "fcf_yield_when_inputs_exist": (value.fcf_yield is not None)
                == (value.market_cap is not None and metadata["fcf_ttm"] is not None),
                "no_future_financial_inputs": all(
                    o.available_at <= trade for o in q.metrics.values()
                ),
                "price_provenance": bool(
                    metadata["price"]
                    and metadata["price"]["provenance"].get("original_response_hash")
                ),
            }
            gates.append(
                {
                    **row,
                    "checks": checks,
                    "sec_stage": sec_stage,
                    "status": "PASS" if all(checks.values()) else "FAIL",
                }
            )
        reviews = review_quality(
            db,
            1,
            now(),
            snapshot_fact_ids={
                row["quarter"]: row["financial_and_valuation_fact_ids"] for row in quarters
            },
        )
        counts = {
            t.name: db.scalar(select(func.count()).select_from(t))
            for t in Base.metadata.sorted_tables
        }
        sec_docs = list(
            db.scalars(select(SourceDocument).where(SourceDocument.source_provider == "SEC"))
        )
        sec_facts_count = db.scalar(
            select(func.count())
            .select_from(FinancialFact)
            .join(SourceDocument)
            .where(SourceDocument.source_provider == "SEC")
        )
        primary_periods = set(
            db.scalars(
                select(Filing.period_end)
                .join(SourceDocument, SourceDocument.filing_id == Filing.id)
                .where(SourceDocument.document_type == "SEC primary filing")
            )
        )
        sec_coverage = {
            "filings": counts["filings"],
            "financial_facts": sec_facts_count,
            "source_documents": len(sec_docs),
            "document_types": dict(Counter(d.document_type for d in sec_docs)),
            "quarters_with_primary_filing": sum(
                repo.quarter(
                    int(r["quarter"][2:6]), int(r["quarter"][-1]), r["valuation_at"]
                ).period_end
                in primary_periods
                for r in quarters
            ),
        }
        hashes = {
            d.id: bool(read_document(d, settings.qve_raw_dir))
            for d in db.scalars(select(SourceDocument))
        }
        db.commit()
        summary = {
            "policy": {
                "minute_boundary": "accepted",
                "research_reconstructed_prices": "accepted",
                "independent_raw_vendor_required": False,
                "wall_street_consensus_required": False,
                "forward_valuation": "deferred",
                "milestone_2_started": False,
            },
            "generated_at": now(),
            "live_sec": live,
            "sec_coverage": sec_coverage,
            "counts": counts,
            "share_observations": counts["share_count_observations"],
            "cover_ingestion": covers,
            "coverage": {
                metric: sum(r[metric] is not None for r in quarters)
                for metric in (
                    "shares",
                    "market_cap",
                    "enterprise_value",
                    "fcf_yield",
                    "trailing_pe",
                )
            },
            "total_quarters": len(quarters),
            "gate_statuses": {g["quarter"]: g["status"] for g in gates},
            "all_source_hashes_verified": all(hashes.values()),
            "source_documents_verified": len(hashes),
        }
        for name, data in (
            ("summary", summary),
            ("quarterly-coverage", quarters),
            ("pm-gates", gates),
            ("reconciliation", reconciliation),
            ("quality-review", reviews),
            ("counts", counts),
        ):
            save(out / f"{name}.json", data)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-sec", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("data/m11-closure/report"))
    args = parser.parse_args()
    print(json.dumps(run(Settings(), args.output, args.live_sec), indent=2, default=str))
