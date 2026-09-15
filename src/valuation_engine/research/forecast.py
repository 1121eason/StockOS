"""Frozen ForecastPolicyV1: interpretable GAAP income statement and cash-flow baseline."""

from dataclasses import dataclass
from typing import Any

from valuation_engine.ingestion.ir import fiscal_start
from valuation_engine.normalization.quarterly import prior_period
from valuation_engine.research.inputs import FinancialInputs, period_name
from valuation_engine.research.numbers import (
    POLICY,
    D,
    EPSForecastShares,
    bound,
    div,
    median,
    p,
    stats,
    total,
)

FIELDS = (
    "revenue",
    "gross_margin",
    "gross_profit",
    "operating_expenses",
    "operating_income",
    "non_operating_income",
    "pre_tax_income",
    "tax_rate",
    "net_income",
    "diluted_weighted_shares",
    "eps",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
)
ADDITIVE = (
    "revenue",
    "gross_profit",
    "operating_expenses",
    "operating_income",
    "non_operating_income",
    "pre_tax_income",
    "net_income",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
)


@dataclass(frozen=True)
class ForecastPolicyV1:
    model: str = "A"

    def __post_init__(self):
        if self.model not in ("A", "B", "C"):
            raise ValueError("Unknown frozen model variant")


def days(fy, fq):
    next_fy, next_fq = prior_period(fy, fq, -1)
    return D((fiscal_start(next_fy, next_fq) - fiscal_start(fy, fq)).days)


def actual_period(data, q):
    if q is None:
        return None

    def v(key):
        return data.value(q, key)

    revenue, gp, oi, pre, ni = (
        v(k) for k in ("revenue", "gross_profit", "operating_income", "pretax_income", "net_income")
    )
    shares = v("diluted_shares")
    values = dict(
        revenue=revenue,
        gross_margin=div(gp, revenue),
        gross_profit=gp,
        operating_expenses=v("operating_expenses"),
        operating_income=oi,
        non_operating_income=pre - oi if pre is not None and oi is not None else None,
        pre_tax_income=pre,
        tax_rate=div(v("tax_expense"), pre),
        net_income=ni,
        diluted_weighted_shares=shares,
        eps=v("eps_diluted"),
        operating_cash_flow=v("ocf"),
        capex=v("capex"),
        free_cash_flow=v("fcf"),
    )
    return dict(
        fiscal_year=q.fiscal_year,
        fiscal_quarter=q.fiscal_quarter,
        period_type="actual",
        **values,
        metadata_json={"kind": "known_actual", "cutoff": data.at, "basis_date": data.basis_date},
    )


def aggregate(rows, kind, fy):
    complete = len(rows) == 4 and all(r is not None for r in rows)
    values = {key: total([r[key] for r in rows]) if complete else None for key in ADDITIVE}
    weights = [days(r["fiscal_year"], r["fiscal_quarter"]) for r in rows] if complete else []
    shares = (
        div(
            total(
                [
                    r["diluted_weighted_shares"] * w
                    if r["diluted_weighted_shares"] is not None
                    else None
                    for r, w in zip(rows, weights, strict=True)
                ]
            ),
            sum(weights, D(0)),
        )
        if complete
        else None
    )
    ni, pre = values["net_income"], values["pre_tax_income"]
    values.update(
        gross_margin=div(values["gross_profit"], values["revenue"]),
        tax_rate=div(pre - ni, pre) if pre is not None and ni is not None else None,
        diluted_weighted_shares=shares,
        eps=div(ni, shares),
    )
    return dict(
        fiscal_year=fy,
        fiscal_quarter=0,
        period_type=kind,
        **values,
        metadata_json={
            "components": [
                dict(
                    period=period_name(r["fiscal_year"], r["fiscal_quarter"]), kind=r["period_type"]
                )
                for r in rows
                if r
            ],
            "eps_formula": "sum net income / day-weighted diluted weighted-average shares on one basis",
            "missing": [k for k, v in values.items() if v is None],
        },
    )


def produce(data: FinancialInputs, policy: ForecastPolicyV1):
    warnings: list[dict[str, Any]] = []
    recent = data.history[: POLICY["recent_window"]]
    val = data.value
    rev = val(data.current, "revenue")
    yoy: list[D] = []
    sequential: list[D] = []
    opex_growth: list[D] = []
    share_growth: list[D] = []
    for q in data.history:
        if not q:
            continue
        before = data.quarter(*prior_period(q.fiscal_year, q.fiscal_quarter))
        year_before = data.quarter(q.fiscal_year - 1, q.fiscal_quarter)
        y = div(val(q, "revenue"), val(year_before, "revenue"))
        s = div(val(q, "revenue"), val(before, "revenue"))
        if q in recent:
            if y is not None:
                yoy.append(y - 1)
            if s is not None:
                sequential.append(s - 1)
            for metric, store in (
                ("operating_expenses", opex_growth),
                ("diluted_shares", share_growth),
            ):
                g = div(val(q, metric), val(before, metric))
                if g is not None:
                    store.append(g - 1)
    seq = bound(
        median(sequential) if sequential else D(0),
        p("sequential_growth_min"),
        p("sequential_growth_max"),
        "sequential_growth",
        warnings,
    )
    yg = median(yoy) if yoy else (1 + seq) ** 4 - 1
    acceleration = yoy[0] - yoy[1] if len(yoy) > 1 else D(0)
    annual_growth = bound(
        p("yoy_weight") * yg
        + p("sequential_weight") * ((1 + seq) ** 4 - 1)
        + p("acceleration_weight") * acceleration,
        p("annual_growth_min"),
        p("annual_growth_max"),
        "annual_growth",
        warnings,
    )
    seasonal = {}
    for fq in range(1, 5):
        sample = []
        for q in data.history:
            if q and q.fiscal_quarter == fq:
                prev = data.quarter(*prior_period(q.fiscal_year, q.fiscal_quarter))
                ratio = div(val(q, "revenue"), val(prev, "revenue"))
                if ratio is not None:
                    sample.append(ratio / (1 + seq))
        seasonal[fq] = bound(
            median(sample) if sample else D(1),
            p("seasonality_min"),
            p("seasonality_max"),
            f"seasonality_Q{fq}",
            warnings,
        )
    gm_series = [div(val(q, "gross_profit"), val(q, "revenue")) for q in recent]
    gm_values = [v for v in gm_series if v is not None]
    gm_trailing = median(gm_values)
    gm_trend = gm_values[0] - gm_values[1] if len(gm_values) > 1 else D(0)
    opex_rate = bound(
        median(opex_growth) if opex_growth else D(0),
        p("opex_growth_min"),
        p("opex_growth_max"),
        "opex_growth",
        warnings,
    )
    shares_rate = (
        bound(
            median(share_growth),
            p("share_growth_min"),
            p("share_growth_max"),
            "share_growth",
            warnings,
        )
        if len(share_growth) >= POLICY["share_min_samples"]
        else D(0)
    )
    if len(share_growth) < POLICY["share_min_samples"]:
        warnings.append(
            {"parameter": "diluted_weighted_shares", "reason": "insufficient_history_flat_baseline"}
        )
    share_base = val(data.current, "diluted_shares")
    nonop: list[D] = []
    tax_samples: list[D] = []
    fcf_margins: list[D] = []
    capex_margins: list[D] = []
    conversions: list[D] = []
    for q in recent:
        r, pre, oi, ni, ocf = (
            val(q, k) for k in ("revenue", "pretax_income", "operating_income", "net_income", "ocf")
        )
        if r and pre is not None and oi is not None:
            nonop.append((pre - oi) / r)
        tax = div(val(q, "tax_expense"), pre) if pre is not None and pre > 0 else None
        if tax is not None and p("tax_min") <= tax <= p("tax_max"):
            tax_samples.append(tax)
        elif q:
            warnings.append(
                {
                    "parameter": "tax_rate",
                    "period": period_name(q.fiscal_year, q.fiscal_quarter),
                    "reason": "missing_nonpositive_pretax_or_abnormal_rate",
                    "raw": tax,
                }
            )
        for metric, store in (("fcf", fcf_margins), ("capex", capex_margins)):
            m = div(val(q, metric), r)
            if m is not None:
                store.append(m)
        if r and ocf is not None and ni is not None:
            conversions.append((ocf - ni) / r)
    nonop_ratio, tax_fallback = median(nonop), median(tax_samples)
    fcf_margin, capex_margin, conversion = (
        median(fcf_margins),
        median(capex_margins),
        median(conversions),
    )
    for metric in ("accounts_receivable", "inventory"):
        ratios = [div(val(q, metric), val(q, "revenue")) for q in recent]
        history = [x for x in ratios[1:] if x is not None]
        if (
            ratios
            and ratios[0] is not None
            and history
            and median(history) > 0
            and ratios[0] > median(history) * p("working_capital_ratio_warning")
        ):
            warnings.append(
                {
                    "parameter": metric,
                    "reason": "working_capital_ratio_anomaly",
                    "latest": ratios[0],
                    "historical_median": median(history),
                    "handling": "cash_conversion_baseline_retained_not_extrapolated_as_precise_working_capital",
                }
            )
    samples = data.guidance_accuracy()
    bias = {}
    for metric, values in samples.items():
        window = values[-POLICY["bias_window"] :]
        errors = [x["surprise"] for x in window]
        enough = len(errors) >= POLICY["bias_min_samples"]
        limit = p("margin_bias_bound") if metric == "gross_margin" else p("relative_bias_bound")
        adjustment = (
            bound(median(errors), -limit, limit, metric + "_bias", warnings) if enough else D(0)
        )
        bias[metric] = {
            **stats(errors),
            "adjustment": adjustment,
            "status": "available" if enough else "insufficient_history",
            "samples": window,
        }
    fy, fq = prior_period(data.anchor[0], data.anchor[1], -1)
    guidance = data.guidance_for(fy, fq)
    guided = {k: g.mid_value for k, g in guidance.items()}
    target = period_name(fy, fq)
    opex_base = val(data.current, "operating_expenses")
    raw_guidance = {k: data.guidance_record(g) for k, g in guidance.items()}
    q1_adjusted = {}
    for metric in ("revenue", "gross_margin", "operating_expenses"):
        raw = guided.get(metric)
        q1_adjusted[metric] = (
            (
                raw + bias[metric]["adjustment"]
                if metric == "gross_margin"
                else raw * (1 + bias[metric]["adjustment"])
            )
            if raw is not None
            else None
        )
    tax = guided.get("tax_rate", tax_fallback)
    if tax is not None and not p("tax_min") <= tax <= p("tax_max"):
        warnings.append(
            {
                "parameter": "tax_guidance",
                "reason": "outside_validation_bounds_fallback",
                "raw": tax,
            }
        )
        tax = tax_fallback
    a_rows: list[dict[str, Any]] = []
    b_rows: list[dict[str, Any]] = []
    for horizon in range(1, POLICY["forecast_quarters"] + 1):
        fy, fq = prior_period(data.anchor[0], data.anchor[1], -horizon)
        growth = p("long_run_growth") + (annual_growth - p("long_run_growth")) * p(
            "growth_persistence"
        ) ** (horizon - 1)
        step = (1 + growth) ** (D(1) / 4) * seasonal[fq]
        for variant, rows in (("A", a_rows), ("B", b_rows)):
            prev_rev = rows[-1]["revenue"] if rows else rev
            r = prev_rev * step if prev_rev is not None else None
            gm_anchor = (
                q1_adjusted["gross_margin"]
                if variant == "A" and q1_adjusted["gross_margin"] is not None
                else (gm_values[0] if gm_values else None)
            )
            gm = (
                gm_trailing
                + (gm_anchor - gm_trailing) * p("margin_persistence") ** (horizon - 1)
                + gm_trend * p("margin_trend_weight") * p("margin_persistence") ** horizon
                if gm_trailing is not None and gm_anchor is not None
                else None
            )
            prev_opex = rows[-1]["operating_expenses"] if rows else opex_base
            ox = (
                prev_opex * (1 + opex_rate * p("opex_persistence") ** (horizon - 1))
                if prev_opex is not None
                else None
            )
            if variant == "A" and horizon == 1:
                r = q1_adjusted["revenue"] if q1_adjusted["revenue"] is not None else r
                gm = q1_adjusted["gross_margin"] if q1_adjusted["gross_margin"] is not None else gm
                ox = (
                    q1_adjusted["operating_expenses"]
                    if q1_adjusted["operating_expenses"] is not None
                    else ox
                )
            gm = bound(gm, D(0), D(1), f"{variant}_Q{horizon}_gross_margin", warnings)
            if gm is not None and not p("margin_warning_low") <= gm <= p("margin_warning_high"):
                warnings.append(
                    {
                        "parameter": f"{variant}_Q{horizon}_gross_margin",
                        "reason": "company_warning_bounds",
                        "value": gm,
                    }
                )
            if r is not None and r <= 0:
                r = None
            if ox is not None and ox < 0:
                warnings.append({"parameter": "opex", "reason": "negative_unavailable"})
                ox = None
            shares = rows[-1]["diluted_weighted_shares"] if rows else share_base
            shares = (
                EPSForecastShares(
                    shares * (1 + shares_rate * p("share_growth_persistence") ** (horizon - 1))
                )
                if shares is not None and shares > 0
                else None
            )
            rows.append(
                financial_row(
                    fy,
                    fq,
                    horizon,
                    r,
                    gm,
                    ox,
                    tax,
                    nonop_ratio,
                    shares,
                    fcf_margin,
                    capex_margin,
                    conversion,
                    warnings,
                )
            )
    if policy.model == "C":
        rows = []
        for a, b in zip(a_rows, b_rows, strict=True):

            def mix(k, a=a, b=b):
                return (
                    p("ensemble_anchor_weight") * a[k] + p("ensemble_trend_weight") * b[k]
                    if a[k] is not None and b[k] is not None
                    else None
                )

            # Blend revenue/gross profit/OpEx, then recalculate the entire income statement.
            r, gp = mix("revenue"), mix("gross_profit")
            rows.append(
                financial_row(
                    a["fiscal_year"],
                    a["fiscal_quarter"],
                    a["metadata_json"]["horizon"],
                    r,
                    div(gp, r),
                    mix("operating_expenses"),
                    tax,
                    nonop_ratio,
                    mix("diluted_weighted_shares"),
                    fcf_margin,
                    capex_margin,
                    conversion,
                    warnings,
                )
            )
    else:
        rows = a_rows if policy.model == "A" else b_rows
    fy1 = data.anchor[0] + (data.anchor[1] == 4)
    periods = list(rows)
    periods.append(aggregate(rows[:4], "NTM", rows[0]["fiscal_year"]))
    for kind, year in (("FY1", fy1), ("FY2", fy1 + 1)):
        components = []
        for quarter in range(1, 5):
            projected = next(
                (r for r in rows if (r["fiscal_year"], r["fiscal_quarter"]) == (year, quarter)),
                None,
            )
            components.append(
                projected
                if projected
                else actual_period(data, data.quarter(year, quarter))
                if (year, quarter) <= data.anchor
                else None
            )
        periods.append(aggregate(components, kind, year))
    actuals = [actual_period(data, q) for q in recent]
    fcff_start = total([fcff_proxy(a) for a in actuals]) if len(actuals) == 4 else None
    for row in periods:
        row["metadata_json"].update(
            basis_date=str(data.basis_date),
            share_semantics="forecast_diluted_weighted_average",
            missing=[k for k in FIELDS if row[k] is None],
        )
    return dict(
        periods=periods,
        metadata=dict(
            anchor=period_name(*data.anchor),
            primary_model="A",
            model_variant=policy.model,
            raw_guidance=raw_guidance,
            bias_adjusted_guidance=q1_adjusted,
            guidance_target=target,
            guidance_bias=bias,
            parameters=dict(
                annual_growth=annual_growth,
                recent_yoy=yg,
                recent_sequential=seq,
                acceleration=acceleration,
                seasonality=seasonal,
                gross_margin_median=gm_trailing,
                gross_margin_trend=gm_trend,
                opex_growth=opex_rate,
                tax_rate=tax,
                non_operating_income_ratio=nonop_ratio,
                share_growth=shares_rate,
                fcf_margin=fcf_margin,
                capex_margin=capex_margin,
                cash_conversion_adjustment=conversion,
            ),
            starting_fcff=fcff_start,
            warnings=warnings + data.warnings,
            provenance=data.provenance(),
        ),
    )


def financial_row(
    fy,
    fq,
    horizon,
    revenue,
    gm,
    opex,
    tax,
    nonop_ratio,
    shares,
    fcf_margin,
    capex_margin,
    conversion,
    warnings,
):
    gp = revenue * gm if revenue is not None and gm is not None else None
    oi = gp - opex if gp is not None and opex is not None else None
    nonop = revenue * nonop_ratio if revenue is not None and nonop_ratio is not None else None
    pre = oi + nonop if oi is not None and nonop is not None else None
    if (
        pre is not None
        and pre < 0
        and tax is not None
        and not POLICY["recognize_forecast_loss_tax_benefit"]
    ):
        warnings.append(
            {
                "parameter": "tax_rate",
                "reason": "forecast_loss_no_tax_benefit_assumed",
                "guided_or_trailing_rate": tax,
            }
        )
        tax = D(0)
    ni = pre * (1 - tax) if pre is not None and tax is not None else None
    capex = (
        revenue * capex_margin
        if revenue is not None and capex_margin is not None and capex_margin >= 0
        else None
    )
    margin_fcf = revenue * fcf_margin if revenue is not None and fcf_margin is not None else None
    conversion_fcf = (
        ni + revenue * conversion - capex
        if ni is not None and revenue is not None and conversion is not None and capex is not None
        else None
    )
    if margin_fcf is not None and conversion_fcf is not None:
        fcf = p("fcf_margin_weight") * margin_fcf + p("cash_conversion_weight") * conversion_fcf
        method = "fixed_margin_cash_conversion_ensemble"
    else:
        fcf = margin_fcf if margin_fcf is not None else conversion_fcf
        method = "single_available_fcf_baseline" if fcf is not None else "unavailable"
    if div(fcf, revenue) is not None and abs(fcf / revenue) > p("fcf_margin_warning_abs"):
        warnings.append(
            {
                "parameter": f"Q{horizon}_fcf_margin",
                "reason": "extreme_unclipped_cash_flow",
                "value": fcf / revenue,
            }
        )
    ocf = fcf + capex if fcf is not None and capex is not None else None
    return dict(
        fiscal_year=fy,
        fiscal_quarter=fq,
        period_type="quarter",
        revenue=revenue,
        gross_margin=gm,
        gross_profit=gp,
        operating_expenses=opex,
        operating_income=oi,
        non_operating_income=nonop,
        pre_tax_income=pre,
        tax_rate=tax,
        net_income=ni,
        diluted_weighted_shares=shares,
        eps=div(ni, shares),
        operating_cash_flow=ocf,
        capex=capex,
        free_cash_flow=fcf,
        metadata_json={
            "horizon": horizon,
            "fcf_method": method,
            "fcf_formula_version": "FCFMarginCashConversionV1",
            "fcf_margin_component": margin_fcf,
            "cash_conversion_component": conversion_fcf,
        },
    )


def fcff_proxy(row):
    if row is None:
        return None
    fcf, ni, oi, tax = (
        row.get(k) for k in ("free_cash_flow", "net_income", "operating_income", "tax_rate")
    )
    return (
        fcf - ni + oi * (1 - tax)
        if all(v is not None for v in (fcf, ni, oi, tax)) and 0 <= tax <= 1
        else None
    )
