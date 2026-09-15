"""Whitelisted, read-only context. No valuation, price, outcome or AI-table queries."""

from sqlalchemy import select

from valuation_engine.db.schema import ForecastPeriod, ForecastRun, RegimeSnapshot
from valuation_engine.regime.confidence import snapshot_contract
from valuation_engine.regime.features import eligible_runs
from valuation_engine.research.numbers import canonical


def resolve_run(db, company_id, quarter=None, cutoff=None):
    if cutoff is None:
        from valuation_engine.time import now

        cutoff = now()
    runs = eligible_runs(db, company_id, cutoff)
    selected = [r for r in runs if quarter is None or r.metadata_json["anchor"] == quarter]
    if not selected:
        raise ValueError("No eligible immutable formal Quant forecast for this quarter/cutoff")
    return selected[-1]


def context_for(db, run):
    if not isinstance(run, ForecastRun):
        raise ValueError("Expected immutable Quant forecast")
    row = db.scalar(
        select(RegimeSnapshot)
        .where(
            RegimeSnapshot.forecast_run_id == run.id,
            RegimeSnapshot.policy_version == "RegimePolicyV1.1",
            RegimeSnapshot.as_of_timestamp <= run.forecast_as_of,
        )
        .order_by(RegimeSnapshot.id.desc())
    )
    if row is None:
        raise ValueError("Run the independent corrected Regime engine first")
    regime = snapshot_contract(row)
    regime.pop("quality_lineage", None)
    periods = list(
        db.scalars(select(ForecastPeriod).where(ForecastPeriod.forecast_run_id == run.id))
    )
    values = [
        {
            k: getattr(p, k)
            for k in (
                "id",
                "period_type",
                "fiscal_year",
                "revenue",
                "eps",
                "free_cash_flow",
                "gross_margin",
                "operating_income",
            )
        }
        for p in periods
    ]
    # Stored guidance samples are already PIT-bound by the immutable M2 run. Recheck dates.
    bias = run.metadata_json["guidance_bias"]
    from datetime import datetime

    for item in bias.values():
        for sample in item.get("samples", []):
            if datetime.fromisoformat(sample["actual_available_at"]) > run.information_cutoff:
                raise ValueError("Future guidance accuracy sample")
    return canonical(
        {
            "company_id": run.company_id,
            "quarter": run.metadata_json["anchor"],
            "forecast_run_id": run.id,
            "as_of_timestamp": run.forecast_as_of,
            "information_cutoff": run.information_cutoff,
            "quant_forecasts": values,
            "regime": regime,
            "quant_guidance_accuracy": bias,
            "anomaly_codes": [
                r
                for r in row.metadata_json["state"]["reason_codes"]
                if r in ("CASH_FLOW_DIVERGENCE", "CYCLICAL_PRESSURE", "MARGIN_COMPRESSION")
            ],
            "fundamental_features": row.metadata_json["inputs"]["features"],
        }
    )
