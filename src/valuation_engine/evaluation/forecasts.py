"""Evaluate frozen forecasts against realized financial facts in a separate label database."""

from collections import defaultdict
from datetime import date

from sqlalchemy import select

from valuation_engine.db.schema import AssumptionSet, ForecastOutcome, ForecastRun
from valuation_engine.db.store import digest
from valuation_engine.research.inputs import FinancialInputs, period_name
from valuation_engine.research.numbers import POLICY, D, canonical, dispersion, div, mean, median, p
from valuation_engine.research.realized import realized_period
from valuation_engine.research.service import METRICS, policy_payload, stored_periods


def errors(predicted, actual):
    if predicted is None or actual is None:
        return None
    error = predicted - actual
    return dict(
        forecast=predicted,
        actual=actual,
        signed_error=error,
        absolute_error=abs(error),
        percentage_error=div(error, abs(actual)),
        absolute_percentage_error=div(abs(error), abs(actual)),
        smape=div(2 * abs(error), abs(actual) + abs(predicted)),
        error_basis_points=error * 10000,
    )


def evaluate(db, labels, as_of):
    data = FinancialInputs(db, 1, as_of)
    observations = []
    current_assumptions = db.scalar(
        select(AssumptionSet).where(AssumptionSet.content_hash == digest(policy_payload()))
    )
    if current_assumptions is None:
        return {
            "observations": [],
            "accuracy": [],
            "guidance_accuracy": {},
            "reason": "No frozen-policy forecasts",
        }
    unique_runs = {}
    for run in db.scalars(
        select(ForecastRun)
        .where(
            ForecastRun.forecast_type == "first_tradable",
            ForecastRun.forecast_as_of <= as_of,
            ForecastRun.model_version == POLICY["version"],
            ForecastRun.assumption_set_id == current_assumptions.id,
        )
        .order_by(ForecastRun.forecast_as_of, ForecastRun.id)
    ):
        unique_runs[
            (
                run.company_id,
                run.model_name,
                run.model_version,
                run.assumption_set_id,
                run.forecast_as_of,
            )
        ] = run
    for run in unique_runs.values():
        for projected in stored_periods(db, run.id):
            kind = projected["period_type"]
            horizon = (
                str(projected["metadata_json"].get("horizon")) + "Q" if kind == "quarter" else kind
            )
            if horizon not in ("1Q", "2Q", "4Q", "FY1", "FY2"):
                continue
            actual, available, ids = realized_period(data, projected)
            if actual is None or available > as_of:
                continue
            factor = data.split.factor(
                date.fromisoformat(projected["metadata_json"]["basis_date"]), data.basis_date
            )
            metric_errors = {}
            for metric in METRICS:
                estimate = projected[metric]
                if metric == "eps" and estimate is not None:
                    estimate /= factor
                metric_errors[metric] = errors(estimate, actual[metric])
            payload = canonical(
                dict(
                    run_id=run.id,
                    run_key=run.identity_key,
                    origin=run.metadata_json["anchor"],
                    model=run.model_name,
                    horizon=horizon,
                    target=period_name(projected["fiscal_year"], projected["fiscal_quarter"])
                    if kind == "quarter"
                    else f"FY{projected['fiscal_year']}",
                    forecast_as_of=run.forecast_as_of,
                    actual_available_at=available,
                    actual_fact_ids=ids,
                    comparison_basis=str(data.basis_date),
                    eps_split_factor=factor,
                    errors=metric_errors,
                    classification="financial_evaluation_label",
                    annual_actual_method="quarterly GAAP income and day-weighted shares reconstruction",
                )
            )
            key = digest([run.identity_key, horizon, payload, "ForecastEvaluationV1"])
            if not labels.scalar(
                select(ForecastOutcome.id).where(ForecastOutcome.identity_key == key)
            ):
                labels.add(
                    ForecastOutcome(
                        identity_key=key,
                        forecast_run_key=run.identity_key,
                        evaluation_as_of=as_of,
                        available_at=available,
                        model_version="ForecastEvaluationV1",
                        horizon=horizon,
                        fiscal_period=payload["target"],
                        metadata_json=payload,
                    )
                )
            observations.append(payload)
    labels.flush()
    return dict(
        evaluation_as_of=canonical(as_of),
        observations=observations,
        accuracy=accuracy(observations),
        guidance_accuracy=canonical(data.guidance_accuracy()),
    )


def accuracy(observations):
    groups = defaultdict(list)
    for row in observations:
        for metric, error in row["errors"].items():
            if error is not None:
                groups[(row["model"], row["horizon"], metric)].append((row, error))
    output = []
    for (model, horizon, metric), values in sorted(groups.items()):
        signed = [D(v["signed_error"]) for _, v in values]
        pct = [
            D(v["absolute_percentage_error"])
            for _, v in values
            if v["absolute_percentage_error"] is not None
        ]
        smape = [D(v["smape"]) for _, v in values if v["smape"] is not None]
        extreme = [
            abs(D(v["percentage_error"])) > p("extreme_relative_error")
            for _, v in values
            if v["percentage_error"] is not None
        ]
        output.append(
            canonical(
                dict(
                    model=model,
                    horizon=horizon,
                    metric=metric,
                    sample_count=len(values),
                    mae=mean([abs(x) for x in signed]),
                    mape=mean(pct),
                    smape=mean(smape),
                    mean_bias=mean(signed),
                    median_bias=median(signed),
                    error_dispersion=dispersion(signed),
                    gm_mae_basis_points=mean([abs(x) * 10000 for x in signed])
                    if metric == "gross_margin"
                    else None,
                    extreme_miss_frequency=D(sum(extreme)) / len(extreme) if extreme else None,
                    worst_errors=[
                        dict(origin=r["origin"], target=r["target"], **v)
                        for r, v in sorted(
                            values, key=lambda pair: abs(D(pair[1]["signed_error"])), reverse=True
                        )[:3]
                    ],
                )
            )
        )
    return output
