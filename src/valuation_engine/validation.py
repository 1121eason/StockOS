from decimal import Decimal

from sqlalchemy.orm import Session

from valuation_engine.db.store import issue
from valuation_engine.normalization.quarterly import Quarter


def validate_quarter(db: Session, q: Quarter) -> dict[str, int]:
    result = {"checked": 0, "failed": 0, "missing": len(q.missing)}
    period = f"FY{q.fiscal_year}-Q{q.fiscal_quarter}"
    for metric in q.missing:
        issue(
            db,
            "missing_metric",
            {"as_of": q.as_of.isoformat()},
            company_id=q.company_id,
            period=period,
            metric=metric,
        )
    for name, a, b, expected in (
        ("gross_profit_identity", "revenue", "cost_of_revenue", "gross_profit"),
        ("fcf_identity", "ocf", "capex", "fcf"),
    ):
        av, bv, ev = q.value(a), q.value(b), q.value(expected)
        if av is None or bv is None or ev is None:
            continue
        result["checked"] += 1
        residual = av - bv - ev
        if abs(residual) > Decimal("2000000"):  # three independently rounded million-USD terms
            result["failed"] += 1
            issue(
                db,
                "accounting_mismatch",
                {"check": name, "residual_usd": str(residual)},
                company_id=q.company_id,
                period=period,
                metric=expected,
                severity="error",
            )
    reported = q.value("company_reported_fcf")
    computed = q.value("fcf")
    if reported is not None and computed is not None and reported != computed:
        issue(
            db,
            "fcf_definition_difference",
            {
                "engine_fcf": str(computed),
                "company_reported_fcf": str(reported),
                "reason": "NVIDIA also deducts equipment/intangible principal payments; engine uses OCF - purchases CapEx",
            },
            company_id=q.company_id,
            period=period,
            metric="fcf",
        )
    return result
