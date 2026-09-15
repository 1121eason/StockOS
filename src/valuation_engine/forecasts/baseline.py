from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import (
    AssumptionSet,
    ForecastSnapshot,
    GuidanceItem,
    QuarterlySnapshot,
)
from valuation_engine.db.store import digest
from valuation_engine.features.engine import divide, growth
from valuation_engine.hardening.availability import AvailabilityResolver
from valuation_engine.normalization.quarterly import Quarter
from valuation_engine.time import aware, now

VERSION = "guidance-baseline-1.0"


def forecast_revision(new: Decimal | None, old: Decimal | None) -> Decimal | None:
    return growth(new, old)


def forecast(db: Session, snapshot: QuarterlySnapshot, as_of: datetime) -> ForecastSnapshot:
    as_of = aware(as_of)
    if snapshot.as_of_timestamp != as_of or snapshot.available_at > as_of:
        raise ValueError(
            "Forecast must use a snapshot reconstructed at exactly the forecast cutoff"
        )
    q = Quarter.model_validate(snapshot.payload)
    fy, fq = (
        (q.fiscal_year + 1, 1) if q.fiscal_quarter == 4 else (q.fiscal_year, q.fiscal_quarter + 1)
    )
    target = f"FY{fy}-Q{fq}"
    rows = db.scalars(
        select(GuidanceItem)
        .where(
            GuidanceItem.company_id == q.company_id,
            GuidanceItem.guidance_for_period.in_((target, f"FY{fy}")),
            GuidanceItem.basis == "GAAP",
        )
        .order_by(GuidanceItem.available_at.desc(), GuidanceItem.id.desc())
    ).all()
    resolver = AvailabilityResolver(db, "guidance")
    rows = sorted(
        (r for r in rows if resolver.time(r) <= as_of),
        key=lambda r: (resolver.time(r), r.id),
        reverse=True,
    )
    from valuation_engine.hardening.guidance import current_guidance_ids

    current_ids = current_guidance_ids(db, q.company_id)
    if current_ids:
        rows = [r for r in rows if r.id in current_ids]
    guidance: dict[str, GuidanceItem] = {}
    for guidance_row in rows:
        if guidance_row.guidance_for_period == target or guidance_row.metric_name == "tax_rate":
            guidance.setdefault(guidance_row.metric_name, guidance_row)
    assumptions: dict[str, object] = {
        "as_of": as_of.isoformat(),
        "source_snapshot_id": snapshot.id,
        "model_version": VERSION,
        "guidance_ids": {k: v.id for k, v in guidance.items()},
        "guidance_target_periods": {k: v.guidance_for_period for k, v in guidance.items()},
        "assumption_policy": "Use GAAP next-quarter guidance; otherwise carry forward latest reported quarter. FCF uses latest FCF/revenue. No terminal/multiple assumptions.",
    }

    def estimate(metric: str, fallback: Decimal | None) -> Decimal | None:
        value = guidance[metric].mid_value if metric in guidance else fallback
        assumptions[metric] = {
            "value": str(value) if value is not None else None,
            "method": "management_guidance"
            if metric in guidance
            else "latest_quarter_carry_forward",
        }
        return value

    revenue = estimate("revenue", q.value("revenue"))
    gm = estimate("gross_margin", divide(q.value("gross_profit"), q.value("revenue")))
    opex = estimate("operating_expenses", q.value("operating_expenses"))
    tax = estimate("tax_rate", divide(q.value("tax_expense"), q.value("pretax_income")))
    oi = (
        revenue * gm - opex if revenue is not None and gm is not None and opex is not None else None
    )
    pretax, historical_oi = q.value("pretax_income"), q.value("operating_income")
    non_op = pretax - historical_oi if pretax is not None and historical_oi is not None else None
    shares = q.value("diluted_shares")
    net = (
        (oi + non_op) * (1 - tax)
        if oi is not None and non_op is not None and tax is not None and 0 <= tax <= 1
        else None
    )
    eps = divide(net, shares)
    fcf_margin = divide(q.value("fcf"), q.value("revenue"))
    projected_fcf = revenue * fcf_margin if revenue is not None and fcf_margin is not None else None
    assumptions.update(
        {
            "nonoperating_income": {
                "value": str(non_op),
                "method": "latest_pretax_minus_operating_income",
            },
            "diluted_shares": {
                "value": str(shares),
                "method": "latest_reported; no assumed repurchases or future splits",
            },
            "fcf_margin": {"value": str(fcf_margin), "method": "latest_quarter"},
            "eps_formula": "((revenue*gross_margin - operating_expenses + nonoperating_income)*(1-tax_rate))/diluted_shares",
            "fact_ids": sorted({i for x in q.metrics.values() for i in x.fact_ids}),
        }
    )
    key = digest(assumptions)
    assumption_set = db.scalar(select(AssumptionSet).where(AssumptionSet.content_hash == key))
    if not assumption_set:
        assumption_set = AssumptionSet(content_hash=key, assumptions=assumptions)
        db.add(assumption_set)
        db.flush()
    row = ForecastSnapshot(
        company_id=q.company_id,
        forecast_as_of=as_of,
        model_version=VERSION,
        forecast_horizon="next_quarter",
        fiscal_period=target,
        revenue=revenue,
        gross_margin=gm,
        operating_margin=divide(oi, revenue),
        eps=eps,
        fcf=projected_fcf,
        assumption_set_id=assumption_set.id,
        source_snapshot_id=snapshot.id,
        generated_kind="historical_replay" if now() - as_of > timedelta(minutes=5) else "live",
    )
    db.add(row)
    db.flush()
    return row


def historical_forecast(
    db: Session, company_id: int, fiscal_period: str, as_of: datetime
) -> ForecastSnapshot | None:
    """Strict actual-vintage estimates; a replay computed today did not exist historically."""
    as_of = aware(as_of)
    return db.scalar(
        select(ForecastSnapshot)
        .where(
            ForecastSnapshot.company_id == company_id,
            ForecastSnapshot.fiscal_period == fiscal_period,
            ForecastSnapshot.forecast_as_of <= as_of,
            ForecastSnapshot.created_at <= as_of,
            ForecastSnapshot.generated_kind == "live",
        )
        .order_by(
            ForecastSnapshot.forecast_as_of.desc(),
            ForecastSnapshot.created_at.desc(),
            ForecastSnapshot.id.desc(),
        )
    )
