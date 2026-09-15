"""PIT forward valuation and strictly prior valuation context, with versioned DCF."""

from datetime import datetime
from typing import Any

from sqlalchemy import select

from valuation_engine.db.schema import (
    DCFScenario,
    ForecastRun,
    ResearchValuation,
    ValuationSnapshot,
)
from valuation_engine.db.store import digest
from valuation_engine.hardening.valuation import historical_value_at
from valuation_engine.research.dcf import DCFModel, ReverseDCFModel, explicit_fcff
from valuation_engine.research.inputs import FinancialInputs
from valuation_engine.research.numbers import (
    POLICY,
    D,
    MarketEquityShares,
    canonical,
    dispersion,
    div,
    mean,
    p,
    quantile,
)
from valuation_engine.research.service import stored_periods


def historical_context(values, current):
    n = len(values)
    if n < POLICY["context_min_samples"] or current is None:
        return dict(
            status="insufficient_history",
            sample_count=n,
            median=None,
            p25=None,
            p75=None,
            percentile=None,
            zscore=None,
        )
    sd = dispersion(values)
    percentile = D(sum(v < current for v in values)) + D("0.5") * sum(v == current for v in values)
    return dict(
        status="available",
        sample_count=n,
        median=quantile(values, D("0.5")),
        p25=quantile(values, D("0.25")),
        p75=quantile(values, D("0.75")),
        percentile=percentile / n,
        zscore=div(current - mean(values), sd),
    )


def positive_ratio(top, bottom):
    return top / bottom if top is not None and bottom is not None and bottom > 0 else None


def build_valuation(db, run):
    if run.forecast_type != "first_tradable":
        raise ValueError("Historical valuation requires first-tradable forecast")
    data = FinancialInputs(db, run.company_id, run.information_cutoff)
    if run.information_cutoff != data.tradable_at:
        raise ValueError("Valuation must use exact primary trade checkpoint")
    base = historical_value_at(db, data.repo, data.current, run.forecast_as_of)
    periods = stored_periods(db, run.id)
    horizons = {r["period_type"]: r for r in periods if r["period_type"] != "quarter"}
    ntm = horizons["NTM"]
    quote = base.metadata_json.get("price")
    if quote and datetime.fromisoformat(quote["available_at"]) != run.tradable_at:
        raise ValueError("First-permitted price mismatch")
    ratios = dict(
        ntm_pe=positive_ratio(base.market_price, ntm["eps"]),
        fy1_pe=positive_ratio(base.market_price, horizons["FY1"]["eps"]),
        fy2_pe=positive_ratio(base.market_price, horizons["FY2"]["eps"]),
        forward_fcf_yield=positive_ratio(ntm["free_cash_flow"], base.market_cap),
        forward_ev_ebit=positive_ratio(base.enterprise_value, ntm["operating_income"]),
    )
    prior = list(
        db.scalars(
            select(ResearchValuation)
            .join(ForecastRun, ResearchValuation.forecast_run_id == ForecastRun.id)
            .where(
                ResearchValuation.company_id == run.company_id,
                ResearchValuation.as_of_timestamp < run.forecast_as_of,
                ResearchValuation.valuation_model_version == POLICY["valuation_version"],
                ForecastRun.model_name == run.model_name,
                ForecastRun.model_version == run.model_version,
                ForecastRun.assumption_set_id == run.assumption_set_id,
            )
            .order_by(ResearchValuation.as_of_timestamp, ResearchValuation.id)
        )
    )
    unique: dict[Any, Any] = {}
    for old in prior:
        unique.setdefault(old.as_of_timestamp, old)
    observations: dict[str, list[D]] = {
        k: []
        for k in ("ntm_pe", "trailing_pe", "fcf_yield", "forward_fcf_yield", "forward_ev_ebit")
    }
    for old in unique.values():
        old_base = db.get(ValuationSnapshot, old.source_valuation_id)
        for metric in observations:
            value = (
                getattr(old_base, metric)
                if metric in ("trailing_pe", "fcf_yield")
                else getattr(old, metric)
            )
            if value is not None:
                observations[metric].append(value)
    current = {**ratios, "trailing_pe": base.trailing_pe, "fcf_yield": base.fcf_yield}
    context = {k: historical_context(v, current[k]) for k, v in observations.items()}
    projection = explicit_fcff(periods)
    balance = base.metadata_json["inputs"]
    cash = D(balance["balance:cash"]["value"]) if "balance:cash" in balance else None
    debt = D(balance["balance:debt"]["value"]) if "balance:debt" in balance else None
    sq = base.metadata_json["shares"]
    shares = MarketEquityShares(D(sq["share_count"])) if sq else None
    scenarios = []
    if projection["status"] == "available":
        for wacc in POLICY["wacc_grid"]:
            for terminal in POLICY["terminal_growth_grid"]:
                scenarios.append(
                    DCFModel().value(
                        projection["cashflows"], cash, debt, shares, D(wacc), D(terminal)
                    )
                )
    valid = [s for s in scenarios if s["status"] == "available"]
    selected = next(
        (
            s
            for s in valid
            if s["wacc"] == p("wacc_base") and s["terminal_growth"] == p("terminal_growth_base")
        ),
        None,
    )
    starting = run.metadata_json.get("starting_fcff")
    starting = D(starting) if starting is not None else None
    reverse = ReverseDCFModel().solve(
        base.enterprise_value, starting, p("wacc_base"), p("terminal_growth_base")
    )
    internal = (
        (projection["cashflows"][-1] / starting) ** (D(1) / POLICY["dcf_years"]) - 1
        if projection["status"] == "available" and starting is not None and starting > 0
        else None
    )
    implied = reverse.get("implied_growth")
    results = dict(
        **ratios,
        historical_ntm_pe_percentile=context["ntm_pe"]["percentile"],
        historical_ntm_pe_zscore=context["ntm_pe"]["zscore"],
        dcf_base=selected["per_share"] if selected else None,
        dcf_low=min(s["per_share"] for s in valid) if valid else None,
        dcf_high=max(s["per_share"] for s in valid) if valid else None,
        reverse_dcf_implied_fcf_cagr=implied,
        internal_fcf_cagr=internal,
        expectations_gap=internal - implied
        if internal is not None and implied is not None
        else None,
    )
    metadata = canonical(
        dict(
            forecast_key=run.identity_key,
            classification=POLICY["classification"],
            historical_context=context,
            context_prior_ids=[r.id for r in unique.values()],
            context_prior_timestamps=[r.as_of_timestamp for r in unique.values()],
            source_valuation=base.metadata_json,
            price=base.market_price,
            market_cap=base.market_cap,
            enterprise_value=base.enterprise_value,
            dcf_projection=projection,
            sensitivity=scenarios,
            reverse_dcf=reverse,
            price_to_dcf=positive_ratio(base.market_price, results["dcf_base"]),
            assumption_set_id=run.assumption_set_id,
            missing=[k for k, v in results.items() if v is None],
        )
    )
    key = digest(canonical([run.identity_key, results, metadata, POLICY["valuation_version"]]))
    existing = db.scalar(select(ResearchValuation).where(ResearchValuation.identity_key == key))
    if existing:
        return existing
    row = ResearchValuation(
        identity_key=key,
        company_id=run.company_id,
        forecast_run_id=run.id,
        source_valuation_id=base.id,
        as_of_timestamp=run.forecast_as_of,
        valuation_model_version=POLICY["valuation_version"],
        **results,
        metadata_json=metadata,
    )
    db.add(row)
    db.flush()
    for scenario in valid:
        db.add(
            DCFScenario(
                valuation_id=row.id,
                wacc=scenario["wacc"],
                terminal_growth=scenario["terminal_growth"],
                enterprise_value=scenario["enterprise_value"],
                equity_value=scenario["equity_value"],
                per_share=scenario["per_share"],
                metadata_json=canonical(
                    {
                        "version": POLICY["dcf_version"],
                        "cashflows": projection["cashflows"],
                        "pit_shares": sq,
                    }
                ),
            )
        )
    db.flush()
    return row
