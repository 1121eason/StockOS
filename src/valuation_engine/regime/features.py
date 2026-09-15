"""PIT financial features from accepted M2 forecasts; no market or label repository."""

from sqlalchemy import select

from valuation_engine.db.schema import AssumptionSet, ForecastRun
from valuation_engine.db.store import digest
from valuation_engine.research.forecast import actual_period, aggregate, days
from valuation_engine.research.inputs import FinancialInputs, period_name
from valuation_engine.research.numbers import D, canonical, div, mean, median
from valuation_engine.research.service import MODELS, policy_payload, stored_periods
from valuation_engine.time import aware

REVISION_METRICS = ("revenue", "eps", "free_cash_flow", "gross_margin", "operating_margin")


def eligible_runs(db, company_id, cutoff):
    rows = list(
        db.scalars(
            select(ForecastRun)
            .join(AssumptionSet)
            .where(
                ForecastRun.company_id == company_id,
                ForecastRun.forecast_as_of <= aware(cutoff),
                ForecastRun.information_cutoff <= aware(cutoff),
                ForecastRun.tradable_at <= aware(cutoff),
                ForecastRun.forecast_type == "first_tradable",
                ForecastRun.model_name == MODELS["A"],
                AssumptionSet.content_hash == digest(policy_payload()),
            )
            .order_by(ForecastRun.forecast_as_of, ForecastRun.id)
        )
    )
    seen = set()
    for row in rows:
        if row.forecast_as_of in seen:
            raise ValueError("Ambiguous formal M2 forecasts at the same checkpoint")
        seen.add(row.forecast_as_of)
    return rows


def extract(db, run, previous_runs, policy, context=None):
    data = FinancialInputs(db, run.company_id, run.information_cutoff)
    if run.forecast_as_of != data.tradable_at:
        raise ValueError("Regime requires the actual first-tradable forecast")
    actuals = [actual_period(data, q) for q in data.history]
    cur, prior, year = actuals[0], actuals[1], actuals[4]
    periods = stored_periods(db, run.id)
    if context is not None:
        context.update(data=data, periods=periods)
    features, warnings, detail = {}, [], {}

    def p(name):
        return D(str(policy[name]))

    def value(row, name):
        if row is None:
            return None
        if name == "operating_margin":
            return div(row["operating_income"], row["revenue"])
        if name == "fcf_margin":
            return div(row["free_cash_flow"], row["revenue"])
        return row.get(name)

    def difference(a, b):
        return a - b if a is not None and b is not None else None

    def growth(a, b, metric, reference, key):
        floor = p("minimum_positive_usd")
        if metric in ("eps", "free_cash_flow"):
            revenue = value(reference, "revenue")
            reference_scale = (
                div(revenue, value(reference, "diluted_weighted_shares"))
                if metric == "eps"
                else revenue
            )
            if reference_scale is None:
                warnings.append({"feature": key, "reason": "unavailable_denominator_reference"})
                return None
            floor = abs(reference_scale) * p("minimum_profit_fraction_of_revenue")
        if a is None or b is None or b <= 0 or b < floor:
            warnings.append({"feature": key, "reason": "missing_nonpositive_or_small_denominator"})
            return None
        return a / b - 1

    for name, metric, base in (
        ("revenue_yoy", "revenue", year),
        ("revenue_qoq", "revenue", prior),
        ("eps_yoy", "eps", year),
        ("fcf_yoy", "free_cash_flow", year),
    ):
        features[name] = growth(value(cur, metric), value(base, metric), metric, base, name)
    features["fcf_growth"] = features["fcf_yoy"]
    prior_yoy = growth(
        value(prior, "revenue"),
        value(actuals[5], "revenue"),
        "revenue",
        actuals[5],
        "prior_revenue_yoy",
    )
    features["growth_acceleration"] = difference(features["revenue_yoy"], prior_yoy)
    ttm = aggregate(actuals[:4], "TTM", data.anchor[0])
    fy1 = next(r for r in periods if r["period_type"] == "FY1")
    last_year = aggregate(
        [actual_period(data, data.quarter(fy1["fiscal_year"] - 1, q)) for q in range(1, 5)],
        "FY",
        fy1["fiscal_year"] - 1,
    )
    for kind, base in (("NTM", ttm), ("FY1", last_year), ("FY2", fy1)):
        row = next(r for r in periods if r["period_type"] == kind)
        for metric in ("revenue", "eps"):
            name = f"{kind.lower()}_{metric}_growth"
            features[name] = growth(row[metric], base[metric], metric, base, name)
    for metric in ("gross_margin", "operating_margin", "fcf_margin"):
        features[metric] = value(cur, metric)
        features[metric + "_change"] = difference(value(cur, metric), value(year, metric))
        if features[metric] is not None and not p("margin_anomaly_lower") <= features[metric] <= p(
            "margin_anomaly_upper"
        ):
            warnings.append({"feature": metric, "reason": "margin_anomaly"})
    revenue_change = difference(value(cur, "revenue"), value(year, "revenue"))
    reliable = (
        revenue_change is not None
        and value(year, "revenue") is not None
        and abs(revenue_change) >= abs(year["revenue"]) * p("minimum_revenue_change_for_leverage")
    )
    features["operating_leverage"] = (
        div(
            difference(value(cur, "operating_income"), value(year, "operating_income")),
            revenue_change,
        )
        if reliable
        else None
    )
    for key, metric in (("ar_growth", "accounts_receivable"), ("inventory_growth", "inventory")):
        a, b = data.value(data.history[0], metric), data.value(data.history[4], metric)
        features[key] = growth(a, b, metric, year, key)
    features["dso"] = div(data.value(data.history[0], "accounts_receivable"), cur["revenue"])
    if features["dso"] is not None:
        features["dso"] *= days(*data.anchor)
    for name, metric in (("capex_to_revenue", "capex"), ("sbc_to_revenue", "sbc")):
        features[name] = div(data.value(data.history[0], metric), cur["revenue"])

    for lag in (1, 2, 4):
        prefix = "" if lag == 1 else f"trailing_{lag}q_"
        older = previous_runs[-lag] if len(previous_runs) >= lag else None
        old_periods = stored_periods(db, older.id) if older else []
        old_fy1 = next((r for r in old_periods if r["period_type"] == "FY1"), None)
        old_quarter = next((r for r in old_periods if r["period_type"] == "quarter"), None)
        new_quarter = next(r for r in periods if r["period_type"] == "quarter")
        consecutive = (
            old_quarter is not None
            and (new_quarter["fiscal_year"] * 4 + new_quarter["fiscal_quarter"])
            - (old_quarter["fiscal_year"] * 4 + old_quarter["fiscal_quarter"])
            == lag
        )
        candidate = (
            next(
                (
                    r
                    for r in old_periods
                    if r["period_type"] in ("FY1", "FY2") and r["fiscal_year"] == fy1["fiscal_year"]
                ),
                None,
            )
            if consecutive
            else None
        )
        factor = (
            data.split.factor(older.information_cutoff.date(), data.basis_date) if older else D(1)
        )
        if candidate:
            candidate = dict(candidate)
            if candidate["eps"] is not None:
                candidate["eps"] /= factor
            if candidate["diluted_weighted_shares"] is not None:
                candidate["diluted_weighted_shares"] *= factor
        available = []
        for metric in REVISION_METRICS:
            alias = "fcf" if metric == "free_cash_flow" else metric
            name = prefix + alias + "_revision"
            a, b = value(fy1, metric), value(candidate, metric)
            features[name] = (
                difference(a, b) if "margin" in metric else growth(a, b, metric, candidate, name)
            )
            if features[name] is not None:
                available.append(features[name])
        features[prefix + "revision_breadth"] = (
            D(sum(v > 0 for v in available)) / len(available) if available else None
        )
        detail[prefix + "revision"] = {
            "previous_run_id": older.id if older else None,
            "same_target": f"FY{fy1['fiscal_year']}",
            "previous_label": candidate["period_type"] if candidate else None,
            "available_metrics": len(available),
            "required_metrics": 5,
            "split_factor": factor,
            "consecutive": consecutive,
            "previous_fy1": old_fy1["fiscal_year"] if old_fy1 else None,
        }

    intervals = next(r for r in periods if r["period_type"] == "quarter")["metadata_json"][
        "intervals"
    ]
    errors, widths, counts = [], [], []
    confidence_detail = {}
    for metric in ("revenue", "eps", "free_cash_flow"):
        band = intervals[metric]
        samples = band["samples"]
        for s in samples:
            from datetime import datetime

            if (
                aware(datetime.fromisoformat(s["origin_as_of"])) >= run.information_cutoff
                or aware(datetime.fromisoformat(s["actual_available_at"])) > run.information_cutoff
            ):
                raise ValueError("Future forecast error sample rejected")
        e = median([abs(D(s["error"])) for s in samples])
        width = (
            div(D(band["upper"]) - D(band["lower"]), abs(D(band["base"])))
            if band["lower"] is not None and band["upper"] is not None and band["base"] is not None
            else None
        )
        counts.append(len(samples))
        if e is not None:
            errors.append(e)
        if width is not None:
            widths.append(width)
        confidence_detail[metric] = {
            "sample_count": len(samples),
            "median_absolute_relative_error": e,
            "relative_interval_width": width,
            "samples": samples,
        }
    features["forecast_error_history"] = mean(errors)
    features["forecast_interval_width"] = mean(widths)
    features["forecast_sample_count"] = D(min(counts))
    warnings.extend(data.warnings)
    for w in run.metadata_json["warnings"]:
        if "basis" in w.get("reason", ""):
            warnings.append(w)
    return canonical(
        {
            "quarter": period_name(*data.anchor),
            "quarter_index": data.anchor[0] * 4 + data.anchor[1],
            "as_of": run.information_cutoff,
            "forecast_run_id": run.id,
            "input_snapshot_id": run.input_snapshot_id,
            "features": features,
            "warnings": warnings,
            "revision_provenance": detail,
            "forecast_confidence": confidence_detail,
            "financial_provenance": data.provenance(),
        }
    )
