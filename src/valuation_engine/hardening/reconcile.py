from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import FinancialFact, ReconciliationResult, SourceDocument
from valuation_engine.db.store import digest
from valuation_engine.hardening.availability import AvailabilityResolver
from valuation_engine.hardening.basis import SplitBasis, fact_basis

CANONICAL_RULE = (
    "PIT originally_reported: earliest eligible information availability; "
    "SEC concept priority only breaks simultaneous ties; "
    "equal-priority conflicting values yield null. "
    "latest_restated is explicit opt-in, never used to rewrite history."
)


def reconcile(db: Session, company_id: int) -> dict[str, int]:
    resolver = AvailabilityResolver(db)
    split = SplitBasis(db, company_id)
    rows = db.execute(
        select(FinancialFact, SourceDocument.source_provider)
        .join(SourceDocument, FinancialFact.source_document_id == SourceDocument.id)
        .where(FinancialFact.company_id == company_id)
    ).all()
    groups: dict[tuple[Any, ...], dict[str, list[FinancialFact]]] = {}
    for fact, provider in rows:
        if provider not in ("SEC", "NVIDIA IR"):
            continue
        group_key = (
            fact.metric_name,
            fact.period_start,
            fact.period_end,
            fact.duration_kind,
        )
        groups.setdefault(group_key, {}).setdefault(provider, []).append(fact)
    counts: Counter[str] = Counter()
    for group in groups.values():
        for ir in group.get("NVIDIA IR", []):
            for sec in group.get("SEC", []):
                key = digest([ir.id, sec.id, "reconciliation-1.1-closure"])
                old = db.scalar(
                    select(ReconciliationResult).where(ReconciliationResult.identity_key == key)
                )
                if old:
                    counts[old.status] += 1
                    continue
                left, right = ir.value, sec.value
                ir_basis, sec_basis = fact_basis(db, ir), fact_basis(db, sec)
                status = "match" if left == right else "conflict"
                if ir.unit != sec.unit:
                    status = "unit_mismatch"
                elif ir.metric_name in ("eps_diluted", "diluted_shares", "period_end_shares"):
                    if ir_basis is None or sec_basis is None:
                        status = "unresolved_basis"
                    else:
                        right = (
                            split.per_share if ir.metric_name == "eps_diluted" else split.shares
                        )(right, sec_basis, ir_basis)
                        status = "split_equivalent" if left == right else "conflict"
                blocking = status in ("conflict", "unresolved_basis", "unit_mismatch")
                db.add(
                    ReconciliationResult(
                        identity_key=key,
                        left_fact_id=ir.id,
                        right_fact_id=sec.id,
                        status=status,
                        blocking=blocking,
                        canonical_rule=CANONICAL_RULE,
                        metadata_json={
                            "metric": ir.metric_name,
                            "version": "reconciliation-1.1-closure",
                            "period_end": str(ir.period_end),
                            "ir_value": str(ir.value),
                            "sec_value": str(sec.value),
                            "ir_unit": ir.unit,
                            "sec_unit": sec.unit,
                            "restatement_candidate": sec.is_restated,
                            "normalized_ir": str(left),
                            "normalized_sec": str(right),
                            "ir_basis": str(ir_basis),
                            "sec_basis": str(sec_basis),
                            "ir_available_at": resolver.time(ir).isoformat(),
                            "sec_available_at": resolver.time(sec).isoformat(),
                            "values_overwritten": False,
                        },
                    )
                )
                counts[status] += 1
    db.flush()
    return dict(counts)


def reconciliation_report(db: Session, company_id: int) -> dict[str, Any]:
    statuses = reconcile(db, company_id)
    metrics = (
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "eps_diluted",
        "ocf",
        "capex",
        "cash",
        "accounts_receivable",
        "inventory",
        "diluted_shares",
    )
    results = list(
        db.scalars(
            select(ReconciliationResult)
            .join(FinancialFact, ReconciliationResult.left_fact_id == FinancialFact.id)
            .where(FinancialFact.company_id == company_id)
        )
    )
    results = [r for r in results if r.metadata_json.get("version") == "reconciliation-1.1-closure"]
    by_metric = {}
    for metric in metrics:
        selected = [r for r in results if r.metadata_json["metric"] == metric]
        counts = dict(Counter(r.status for r in selected))
        ir = list(
            db.scalars(
                select(FinancialFact)
                .join(SourceDocument)
                .where(
                    FinancialFact.company_id == company_id,
                    FinancialFact.metric_name == metric,
                    SourceDocument.source_provider == "NVIDIA IR",
                )
            )
        )
        compared = {r.left_fact_id for r in selected}
        by_metric[metric] = {
            "status_counts": counts,
            "unavailable_ir_fact_ids": [f.id for f in ir if f.id not in compared],
            "comparison_ids": [r.id for r in selected],
        }
    return {
        "canonical_rule": CANONICAL_RULE,
        "status_counts": statuses,
        "matched_pairs": statuses.get("match", 0) + statuses.get("split_equivalent", 0),
        "conflicts": statuses.get("conflict", 0),
        "unit_mismatches": statuses.get("unit_mismatch", 0),
        "basis_mismatches_or_unknown": statuses.get("unresolved_basis", 0),
        "unavailable_comparisons": sum(
            len(v["unavailable_ir_fact_ids"]) for v in by_metric.values()
        ),
        "restatement_candidate_pairs": sum(
            bool(r.metadata_json.get("restatement_candidate")) for r in results
        ),
        "verified_accounting_restatements": None,
        "restatement_policy": "A later differing observation is a candidate; split/presentation changes are not proof of accounting restatement",
        "metrics": by_metric,
    }
