"""Immutable research forecast persistence and PIT calibration from realized financial facts.

Evaluation labels are deliberately not imported. Past error bands are recomputed here from
prior immutable internal forecasts and financial observations eligible at the new cutoff.
"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import select

from valuation_engine.db.schema import (
    AssumptionSet,
    ForecastAssumption,
    ForecastPeriod,
    ForecastRevision,
    ForecastRun,
)
from valuation_engine.db.store import digest
from valuation_engine.research.forecast import FIELDS, ForecastPolicyV1, produce
from valuation_engine.research.inputs import FinancialInputs, period_name
from valuation_engine.research.numbers import POLICY, D, canonical, div, p, quantile, stats

MODELS = {
    "A": "Guidance Anchored Baseline",
    "B": "Mechanical Historical Trend",
    "C": "Fixed Deterministic Ensemble",
}
METRICS = ("revenue", "gross_margin", "operating_income", "eps", "free_cash_flow")


def period_dict(row):
    return {
        "id": row.id,
        "fiscal_year": row.fiscal_year,
        "fiscal_quarter": row.fiscal_quarter,
        "period_type": row.period_type,
        **{k: getattr(row, k) for k in FIELDS},
        "metadata_json": row.metadata_json,
    }


def stored_periods(db, run_id):
    return [
        period_dict(r)
        for r in db.scalars(
            select(ForecastPeriod)
            .where(ForecastPeriod.forecast_run_id == run_id)
            .order_by(ForecastPeriod.id)
        )
    ]


def policy_payload():
    units = {}
    for name, value in POLICY.items():
        units[name] = (
            "boolean"
            if isinstance(value, bool)
            else "decimal_places"
            if name == "decimal_places"
            else "iterations"
            if "iterations" in name
            else "years"
            if name == "dcf_years"
            else "quarters"
            if "quarters" in name or "window" in name
            else "observations"
            if "samples" in name
            else "timestamp"
            if name == "effective_from"
            else "identifier"
            if name.endswith("version") or name == "classification"
            else "dimensionless_ratio"
        )
    return {**POLICY, "parameter_units": units, "storage_version": "typed-assumptions-v1"}


def assumption_set(db):
    payload = policy_payload()
    key = digest(payload)
    row = db.scalar(select(AssumptionSet).where(AssumptionSet.content_hash == key))
    if row:
        return row
    row = AssumptionSet(content_hash=key, assumptions=payload)
    db.add(row)
    db.flush()
    for name, value in sorted(POLICY.items()):
        db.add(
            ForecastAssumption(
                assumption_set_id=row.id,
                parameter_name=name,
                parameter_value=value,
                unit=payload["parameter_units"][name],
                source_type="fixed_research_policy_not_return_fitted",
                source_reference="research/policy_v1.json; docs/FORECAST_METHOD.md; docs/VALUATION_METHOD.md",
                effective_from=datetime.fromisoformat(
                    POLICY["effective_from"].replace("Z", "+00:00")
                ),
                model_version=POLICY["version"],
            )
        )
    db.flush()
    return row


def calibration(data, model, assumptions):
    buckets: dict[Any, list[Any]] = {}
    earlier = list(
        data.db.scalars(
            select(ForecastRun)
            .where(
                ForecastRun.company_id == data.company_id,
                ForecastRun.forecast_as_of < data.at,
                ForecastRun.forecast_type == "first_tradable",
                ForecastRun.model_name == MODELS[model],
                ForecastRun.model_version == POLICY["version"],
                ForecastRun.assumption_set_id == assumptions.id,
            )
            .order_by(ForecastRun.forecast_as_of, ForecastRun.id)
        )
    )
    # One immutable vintage per model/origin; additional same-origin reruns are not independent samples.
    unique: dict[Any, Any] = {}
    for run in earlier:
        unique.setdefault(run.metadata_json["anchor"], run)
    for run in unique.values():
        if run.metadata_json["anchor"] == period_name(*data.anchor):
            continue
        for predicted in stored_periods(data.db, run.id):
            from valuation_engine.research.realized import realized_period

            actual, actual_available, actual_ids = realized_period(data, predicted)
            if (
                actual is None
                or actual_available is None
                or not run.information_cutoff < actual_available <= data.at
            ):
                continue
            horizon = predicted["metadata_json"].get("horizon", predicted["period_type"])
            target = (predicted["fiscal_year"], predicted["fiscal_quarter"])
            factor = data.split.factor(
                date.fromisoformat(predicted["metadata_json"]["basis_date"]), data.basis_date
            )
            for metric in METRICS:
                old = predicted[metric]
                if metric == "eps" and old is not None:
                    old /= factor
                realized = actual[metric]
                if old is None or realized is None or (metric != "gross_margin" and old <= 0):
                    continue
                error = realized - old if metric == "gross_margin" else realized / old - 1
                buckets.setdefault((horizon, metric), []).append(
                    dict(
                        origin_run_id=run.id,
                        origin_as_of=run.forecast_as_of,
                        target=period_name(*target),
                        actual_available_at=actual_available,
                        error=error,
                        actual_fact_ids=actual_ids,
                    )
                )
    return buckets


def build_forecast(db, company_id, at, checkpoint="first_tradable", model="A", data=None):
    if checkpoint not in ("issuer_release", "first_tradable", "research_replay", "live"):
        raise ValueError("Unsupported forecast checkpoint")
    data = data or FinancialInputs(db, company_id, at)
    if data.at != at:
        raise ValueError("Forecast context cutoff mismatch")
    if checkpoint == "first_tradable" and at != data.tradable_at:
        raise ValueError(
            "first_tradable requires the exact first permitted timestamp; use research_replay for another cutoff"
        )
    # Hash an instant using the same representation as the historical coordinator.
    # Equivalent UTC/ET CLI inputs must reuse its immutable checkpoint record.
    at = data.tradable_at if checkpoint == "first_tradable" else data.at
    data.inputs = {}
    data.warnings = []
    assumptions = assumption_set(db)
    result = produce(data, ForecastPolicyV1(model))
    past = calibration(data, model, assumptions)
    for period in result["periods"]:
        intervals = {}
        horizon = period["metadata_json"].get("horizon", period["period_type"])
        for metric in METRICS:
            samples = past.get((horizon, metric), [])
            errors = [r["error"] for r in samples]
            enough = (
                len(errors) >= POLICY["interval_min_samples"]
                and period[metric] is not None
                and (metric == "gross_margin" or period[metric] > 0)
            )
            lower, upper, center = None, None, None
            if enough:
                lo, hi = (
                    quantile(errors, p("interval_quantile_low")),
                    quantile(errors, p("interval_quantile_high")),
                )
                med = quantile(errors, D("0.5"))
                base = period[metric]
                lower, upper, center = (
                    (base + lo, base + hi, base + med)
                    if metric == "gross_margin"
                    else (base * (1 + lo), base * (1 + hi), base * (1 + med))
                )
            intervals[metric] = {
                **stats(errors),
                "status": "empirical_P80" if enough else "insufficient_history",
                "base": period[metric],
                "lower": lower,
                "upper": upper,
                "p50": center,
                "samples": samples,
                "method": "PIT realized financial error recomputation; never evaluation-label database",
            }
        period["metadata_json"]["intervals"] = intervals
    result["metadata"]["provenance"] = data.provenance()
    result["metadata"]["warnings"] = list(
        {digest(w): w for w in result["metadata"]["warnings"] + data.warnings}.values()
    )
    snapshot = data.repo.save(data.current)
    payload = canonical(
        {
            "forecast_as_of": at,
            "information_cutoff": at,
            "tradable_at": data.tradable_at,
            "checkpoint": checkpoint,
            "basis": "GAAP",
            "model": model,
            "model_version": POLICY["version"],
            "assumptions": assumptions.content_hash,
            "input_snapshot_id": snapshot.id,
            **result,
        }
    )
    key = digest(payload)
    existing = db.scalar(select(ForecastRun).where(ForecastRun.identity_key == key))
    if existing:
        return existing
    row = ForecastRun(
        identity_key=key,
        company_id=company_id,
        forecast_as_of=at,
        information_cutoff=at,
        tradable_at=data.tradable_at,
        forecast_type=checkpoint,
        forecast_basis="GAAP",
        generated_kind=POLICY["classification"],
        model_name=MODELS[model],
        model_version=POLICY["version"],
        assumption_set_id=assumptions.id,
        input_snapshot_id=snapshot.id,
        metadata_json=payload["metadata"],
    )
    db.add(row)
    db.flush()
    for period in payload["periods"]:
        db.add(
            ForecastPeriod(
                forecast_run_id=row.id,
                **{k: (D(v) if k in FIELDS and v is not None else v) for k, v in period.items()},
            )
        )
    db.flush()
    return row


def revisions(db, run):
    previous = db.scalar(
        select(ForecastRun)
        .where(
            ForecastRun.company_id == run.company_id,
            ForecastRun.forecast_as_of < run.forecast_as_of,
            ForecastRun.forecast_type == run.forecast_type,
            ForecastRun.model_name == run.model_name,
            ForecastRun.model_version == run.model_version,
            ForecastRun.assumption_set_id == run.assumption_set_id,
        )
        .order_by(ForecastRun.forecast_as_of.desc(), ForecastRun.id)
    )
    if previous is None:
        return {"status": "no_previous_forecast"}
    return compare_forecasts(db, run, previous)


def compare_forecasts(db, run, previous):
    """Compare identical fiscal targets with an explicitly selected prior quarter."""
    if (
        previous.company_id != run.company_id
        or previous.forecast_as_of >= run.forecast_as_of
        or previous.information_cutoff > run.information_cutoff
        or previous.model_name != run.model_name
        or previous.model_version != run.model_version
        or previous.assumption_set_id != run.assumption_set_id
    ):
        raise ValueError("Forecast comparison requires a prior matching model and policy")
    key = digest([previous.identity_key, run.identity_key, "ForecastRevisionV1"])
    oldrow = db.scalar(select(ForecastRevision).where(ForecastRevision.identity_key == key))
    if oldrow:
        return oldrow.metadata_json
    old, new = stored_periods(db, previous.id), stored_periods(db, run.id)
    data = FinancialInputs(db, run.company_id, run.information_cutoff)
    prior_basis = date.fromisoformat(previous.metadata_json["provenance"]["basis_date"])
    factor = data.split.factor(prior_basis, data.basis_date)
    result = []
    for cur in new:
        candidates = [
            r
            for r in old
            if (r["fiscal_year"], r["fiscal_quarter"])
            == (cur["fiscal_year"], cur["fiscal_quarter"])
            and (
                (r["period_type"] == "quarter" and cur["period_type"] == "quarter")
                or (r["period_type"] in ("FY1", "FY2") and cur["period_type"] in ("FY1", "FY2"))
            )
        ]
        if not candidates:
            continue
        prior = candidates[0]
        metrics = {}
        for metric in (*METRICS, "operating_margin"):
            a = (
                div(cur["operating_income"], cur["revenue"])
                if metric == "operating_margin"
                else cur[metric]
            )
            b = (
                div(prior["operating_income"], prior["revenue"])
                if metric == "operating_margin"
                else prior[metric]
            )
            if metric == "eps" and b is not None:
                b /= factor
            delta = a - b if a is not None and b is not None else None
            margin = metric in ("gross_margin", "operating_margin")
            metrics[metric] = dict(
                previous=b,
                current=a,
                absolute_revision=delta,
                percentage_revision=None
                if margin
                else div(delta, abs(b))
                if b is not None
                else None,
                percentage_point_revision=delta * 100 if margin and delta is not None else None,
            )
        result.append(
            dict(
                target=f"FY{cur['fiscal_year']}"
                if cur["fiscal_quarter"] == 0
                else period_name(cur["fiscal_year"], cur["fiscal_quarter"]),
                previous_label=prior["period_type"],
                new_label=cur["period_type"],
                metrics=metrics,
                reasons=["new_quarterly_data", "new_guidance"]
                + (
                    ["fiscal_year_model_roll"] if prior["period_type"] != cur["period_type"] else []
                ),
            )
        )
    payload = canonical(
        dict(
            status="available",
            previous_run_id=previous.id,
            forecast_run_id=run.id,
            split_factor=factor,
            comparisons=result,
            ntm_note="Rolling NTM windows differ; revisions compare identical fiscal targets only",
        )
    )
    db.add(
        ForecastRevision(
            identity_key=key,
            previous_run_id=previous.id,
            forecast_run_id=run.id,
            metadata_json=payload,
        )
    )
    db.flush()
    return payload
