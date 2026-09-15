from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import FinancialFact, ValuationSnapshot
from valuation_engine.db.store import digest
from valuation_engine.hardening.basis import SplitBasis, get_price_as_reported
from valuation_engine.hardening.shares import get_latest_known_shares
from valuation_engine.normalization.quarterly import PointInTimeRepository, Quarter, prior_period
from valuation_engine.time import ET, aware, calculate_next_tradable_timestamp


def historical_value_at(
    db: Session, repo: PointInTimeRepository, q: Quarter, as_of: datetime
) -> ValuationSnapshot:
    from valuation_engine.valuation.ratios import basic_ratios

    at = aware(as_of)
    if q.as_of != at:
        raise ValueError("Valuation snapshot cutoff mismatch")
    first_trade = calculate_next_tradable_timestamp(max(o.available_at for o in q.metrics.values()))
    marks = [get_price_as_reported(db, q.company_id, at, field) for field in ("open", "close")]
    eligible_marks = [mark for mark in marks if mark and mark["available_at"] >= first_trade]
    quote = max(eligible_marks, key=lambda mark: mark["available_at"]) if eligible_marks else None
    split = SplitBasis(db, q.company_id)
    target = at.astimezone(ET).date()
    quarters = [q] + [
        repo.quarter(*prior_period(q.fiscal_year, q.fiscal_quarter, n), at) for n in (1, 2, 3)
    ]
    inputs: dict[str, Any] = {}
    missing = []

    def value(quarter: Quarter | None, metric: str) -> Decimal | None:
        if quarter is None or metric not in quarter.metrics:
            missing.append(f"{metric}:missing_quarter_or_metric")
            return None
        obs = quarter.metrics[metric]
        key = f"FY{quarter.fiscal_year}-Q{quarter.fiscal_quarter}:{metric}"
        inputs[key] = obs.model_dump(mode="json")
        if metric in ("eps_diluted", "period_end_shares", "diluted_shares"):
            basis = obs.metadata.get("share_basis_date")
            if not basis:
                missing.append(key + ":unverified_share_basis")
                return None
            start = date.fromisoformat(basis)
            factor = split.factor(start, target)
            inputs[key]["normalization"] = {
                "from": basis,
                "to": str(target),
                "share_factor": str(factor),
            }
            return obs.value / factor if metric == "eps_diluted" else obs.value * factor
        return obs.value

    def ttm(metric: str) -> Decimal | None:
        values = [value(quarter, metric) for quarter in quarters]
        return (
            sum((v for v in values if v is not None), Decimal(0))
            if all(v is not None for v in values)
            else None
        )

    eps, fcf, ebit, da = (
        ttm(metric)
        for metric in ("eps_diluted", "fcf", "operating_income", "depreciation_amortization")
    )
    share_quote = get_latest_known_shares(db, q.company_id, at)
    shares = share_quote["share_count"] if share_quote else None
    if share_quote is None:
        missing.append("shares_outstanding:no_eligible_observation_or_conflicting_observations")

    def balance(metric: str) -> Decimal | None:
        # Retain the latest published balance, with its economic date and source timestamp.
        periods = db.execute(
            select(FinancialFact.fiscal_year, FinancialFact.fiscal_quarter)
            .where(
                FinancialFact.company_id == q.company_id, FinancialFact.period_end <= q.period_end
            )
            .distinct()
            .order_by(FinancialFact.fiscal_year.desc(), FinancialFact.fiscal_quarter.desc())
        ).all()
        for fy, fq in periods:
            candidate = (
                q if (fy, fq) == (q.fiscal_year, q.fiscal_quarter) else repo.quarter(fy, fq, at)
            )
            obs = candidate.metrics.get(metric) if candidate else None
            if candidate is not None and obs is not None and obs.available_at <= at:
                inputs[f"balance:{metric}"] = {
                    **obs.model_dump(mode="json"),
                    "period_end": str(candidate.period_end),
                    "quarter": f"FY{fy}-Q{fq}",
                    "carried_forward": candidate.period_end != q.period_end,
                }
                return obs.value
        missing.append(f"{metric}:no_known_balance")
        return None

    cash, debt = balance("cash"), balance("debt")
    ratios = (
        basic_ratios(
            price=quote["value"],
            shares=shares,
            cash=cash,
            debt=debt,
            eps_ttm=eps,
            fcf_ttm=fcf,
            ebit_ttm=ebit,
            da_ttm=da,
        )
        if quote
        else {}
    )
    # Annual forward estimates require contemporaneous capture AND explicit per-share basis.
    # The existing baseline supplies neither an annual estimate nor this contract.
    metadata = {
        "kind": "research_reconstructed_valuation",
        "price": quote,
        "basis": "as_traded_at_valuation_date",
        "basis_date": str(target),
        "inputs": inputs,
        "eps_ttm_normalized": str(eps) if eps is not None else None,
        "fcf_ttm": str(fcf) if fcf is not None else None,
        "missing_reasons": sorted(set(missing)),
        "shares": share_quote,
        "share_policy": "latest eligible shares outstanding by economic date and source priority; weighted average never substituted",
        "calculation_version": "ratios-1.1-closure",
        "ev_completeness": "complete"
        if quote and shares is not None and cash is not None and debt is not None
        else "unavailable",
        "ev_missing_components": [
            name
            for name, v in (("price", quote), ("shares", shares), ("cash", cash), ("debt", debt))
            if v is None
        ],
        "fcf_definition_version": "engine-fcf-1.0: operating cash flow minus reported capex",
        "ev_definition": "market_cap + total debt - cash and cash equivalents",
        "forward_status": "Not required for M1.1 closure; internal deterministic forward valuation remains deferred",
        "first_open_policy": "Opening price is execution observation; same-day HLC excluded",
        "corporate_action_ids": [a.id for a in split.actions],
    }
    # JSON stores canonical decimal/time strings, identically on SQLite/PostgreSQL.
    import json

    metadata = json.loads(json.dumps(metadata, default=str))
    key = digest([q.model_dump(mode="json"), metadata, "ratios-1.1-closure"])
    for existing in db.scalars(
        select(ValuationSnapshot).where(
            ValuationSnapshot.company_id == q.company_id,
            ValuationSnapshot.as_of_timestamp == at,
            ValuationSnapshot.model_version == "ratios-1.1-closure",
        )
    ):
        if existing.metadata_json.get("identity_key") == key:
            return existing
    row = ValuationSnapshot(
        company_id=q.company_id,
        as_of_timestamp=at,
        **ratios,
        fy1_pe=None,
        fy2_pe=None,
        model_version="ratios-1.1-closure",
        metadata_json={**metadata, "identity_key": key},
    )
    db.add(row)
    db.flush()
    return row
