import json
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import MarketPrice, ValuationSnapshot
from valuation_engine.features.engine import divide, split_epoch
from valuation_engine.forecasts.baseline import historical_forecast
from valuation_engine.hardening.shares import get_latest_known_shares
from valuation_engine.normalization.quarterly import PointInTimeRepository, Quarter, prior_period
from valuation_engine.time import ET, aware


def basic_ratios(
    *,
    price: Decimal,
    shares: Decimal | None,
    cash: Decimal | None,
    debt: Decimal | None,
    eps_ttm: Decimal | None,
    fcf_ttm: Decimal | None,
    ebit_ttm: Decimal | None,
    da_ttm: Decimal | None = None,
) -> dict[str, Decimal | None]:
    if price <= 0:
        raise ValueError("Price must be positive")
    cap = price * shares if shares is not None and shares > 0 else None
    ev = cap + debt - cash if cap is not None and debt is not None and cash is not None else None
    ebitda = ebit_ttm + da_ttm if ebit_ttm is not None and da_ttm is not None else None
    return {
        "market_price": price,
        "market_cap": cap,
        "enterprise_value": ev,
        "trailing_pe": divide(price, eps_ttm),
        "fcf_yield": divide(fcf_ttm, cap),
        "ev_ebit": divide(ev, ebit_ttm),
        "ev_ebitda": divide(ev, ebitda),
    }


def value_at(
    db: Session, repo: PointInTimeRepository, q: Quarter, as_of: datetime
) -> ValuationSnapshot:
    from valuation_engine.db.schema import PriceBasis

    if db.scalar(select(PriceBasis.id).limit(1)):
        from valuation_engine.hardening.valuation import historical_value_at

        return historical_value_at(db, repo, q, as_of)
    as_of = aware(as_of)
    if q.as_of != as_of:
        raise ValueError("Valuation snapshot cutoff mismatch")
    # Reject current-vintage adjusted price backfills in a historical fundamentals valuation.
    price = db.scalar(
        select(MarketPrice)
        .where(
            MarketPrice.company_id == q.company_id,
            MarketPrice.available_at <= as_of,
            MarketPrice.retrieved_at <= as_of,
            MarketPrice.price_type == "daily_unadjusted",
        )
        .order_by(MarketPrice.available_at.desc(), MarketPrice.retrieved_at.desc())
    )
    quarters = [q] + [
        repo.quarter(*prior_period(q.fiscal_year, q.fiscal_quarter, n), as_of) for n in (1, 2, 3)
    ]

    def ttm(metric: str) -> Decimal | None:
        values = [x.value(metric) if x else None for x in quarters]
        if any(x is None for x in values):
            return None
        if metric == "eps_diluted" and len({split_epoch(x.period_end) for x in quarters if x}) > 1:
            return None
        return sum((x for x in values if x is not None), Decimal(0))

    share_quote = (
        get_latest_known_shares(
            db, q.company_id, as_of, basis_date=price.timestamp.astimezone(ET).date()
        )
        if price
        else None
    )
    metadata = {
        "snapshot_as_of": as_of.isoformat(),
        "price_id": price.id if price else None,
        "missing_price_reason": None
        if price
        else "No contemporaneously observed unadjusted price; bootstrap vendor-adjusted prices are prohibited",
        "ev_definition": "market_cap + current/noncurrent debt - cash_and_equivalents; no security haircut assumptions",
        "share_policy": "latest eligible shares outstanding, normalized to the raw price date",
        "shares": json.loads(json.dumps(share_quote, default=str)),
    }
    ratios = (
        basic_ratios(
            price=price.close,
            shares=share_quote["share_count"] if share_quote else None,
            cash=q.value("cash"),
            debt=q.value("debt"),
            eps_ttm=ttm("eps_diluted"),
            fcf_ttm=ttm("fcf"),
            ebit_ttm=ttm("operating_income"),
            da_ttm=ttm("depreciation_amortization"),
        )
        if price
        else {}
    )
    forward: dict[str, Decimal | None] = {}
    for n in (1, 2):
        forecast = historical_forecast(db, q.company_id, f"FY{q.fiscal_year + n}", as_of)
        forward[f"fy{n}_pe"] = (
            divide(price.close, forecast.eps)
            if forecast and forecast.forecast_horizon == "fiscal_year" and price
            else None
        )
        metadata[f"fy{n}_forecast_id"] = forecast.id if forecast else None
    row = ValuationSnapshot(
        company_id=q.company_id,
        as_of_timestamp=as_of,
        **ratios,
        **forward,
        model_version="ratios-1.1-closure-raw-price",
        metadata_json=metadata,
    )
    db.add(row)
    db.flush()
    return row
