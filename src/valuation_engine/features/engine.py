from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import QuantFeature, QuarterlySnapshot
from valuation_engine.normalization.quarterly import PointInTimeRepository, Quarter, prior_period

VERSION = "features-1.1"
D = Decimal


def divide(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return a / b if a is not None and b is not None and b > 0 else None


def growth(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    ratio = divide(current, previous)
    return ratio - 1 if ratio is not None else None


def difference(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return a - b if a is not None and b is not None else None


def fcf(ocf: Decimal, capex: Decimal) -> Decimal:
    if capex < 0:
        raise ValueError("CapEx must be positive cash outflow")
    return ocf - capex


def dso(
    revenue: Decimal | None, ending_ar: Decimal | None, beginning_ar: Decimal | None, days: int
) -> tuple[Decimal | None, dict[str, Any]]:
    average = (
        (ending_ar + beginning_ar) / 2
        if ending_ar is not None and beginning_ar is not None
        else ending_ar
    )
    result = divide(average, revenue)
    return (result * days if result is not None else None), {
        "approximation": beginning_ar is None,
        "balance_method": "ending_balance" if beginning_ar is None else "average_beginning_ending",
        "days_in_period": days,
    }


@dataclass(frozen=True)
class FeatureSet:
    values: dict[str, Decimal | None]
    metadata: dict[str, Any]
    anomalies: tuple[str, ...]


def compute(repo: PointInTimeRepository, q: Quarter) -> FeatureSet:
    previous = repo.quarter(*prior_period(q.fiscal_year, q.fiscal_quarter), q.as_of)
    year_ago = repo.quarter(q.fiscal_year - 1, q.fiscal_quarter, q.as_of)

    def val(quarter: Quarter | None, metric: str) -> Decimal | None:
        return quarter.value(metric) if quarter else None

    def margin(quarter: Quarter | None, metric: str) -> Decimal | None:
        return divide(val(quarter, metric), val(quarter, "revenue"))

    values: dict[str, Decimal | None] = {}
    meta: dict[str, Any] = {
        "growth_policy": "current / previous - 1; NULL when base <= 0",
        "change_units": "ratio_points",
        "version": VERSION,
        "fact_ids": sorted(
            {
                i
                for x in (q, previous, year_ago)
                if x
                for o in x.metrics.values()
                for i in o.fact_ids
            }
        ),
    }
    for metric, feature in (
        ("revenue", "revenue"),
        ("eps_diluted", "eps"),
        ("fcf", "fcf"),
        ("accounts_receivable", "accounts_receivable"),
        ("inventory", "inventory"),
    ):
        for lag, other in (("yoy", year_ago), ("qoq", previous)):
            if metric in ("accounts_receivable", "inventory") and lag == "qoq":
                continue
            if (
                metric == "eps_diluted"
                and other
                and metric in q.metrics
                and metric in other.metrics
            ):
                current_basis = q.metrics[metric].metadata.get("share_basis_date")
                previous_basis = other.metrics[metric].metadata.get("share_basis_date")
                if current_basis and previous_basis:
                    from datetime import date

                    target_basis = date.fromisoformat(current_basis)
                    normalized_prior = repo.normalize_eps(other.metrics[metric], target_basis)
                    values[f"{feature}_{lag}"] = growth(q.value(metric), normalized_prior)
                    meta[f"{feature}_{lag}"] = {
                        "basis_date": current_basis,
                        "previous_basis_date": previous_basis,
                        "normalized_previous_eps": str(normalized_prior),
                        "policy": "formal corporate actions",
                    }
                    continue
            # Legacy synthetic observations retain conservative cross-split behavior.
            if (
                metric == "eps_diluted"
                and other
                and split_epoch(q.period_end) != split_epoch(other.period_end)
            ):
                values[f"{feature}_{lag}"] = None
                meta[f"{feature}_{lag}"] = (
                    "Unavailable: corporate-action adjustment not verified in M1"
                )
            else:
                values[f"{feature}_{lag}"] = growth(q.value(metric), val(other, metric))
    for metric, feature in (
        ("gross_profit", "gross_margin"),
        ("operating_income", "operating_margin"),
    ):
        values[feature] = margin(q, metric)
        values[feature + "_yoy_change"] = difference(margin(q, metric), margin(year_ago, metric))
        if feature == "gross_margin":
            values[feature + "_qoq_change"] = difference(
                margin(q, metric), margin(previous, metric)
            )
    values["fcf"] = q.value("fcf")
    values["fcf_margin"] = margin(q, "fcf")
    values["capex_to_revenue"] = margin(q, "capex")
    values["sbc_to_revenue"] = margin(q, "sbc")
    if q.period_start:
        days = (q.period_end - q.period_start).days + 1
        values["dso"], meta["dso"] = dso(
            q.value("revenue"),
            q.value("accounts_receivable"),
            val(previous, "accounts_receivable"),
            days,
        )
        values["inventory_days"], meta["inventory_days"] = dso(
            q.value("cost_of_revenue"), q.value("inventory"), val(previous, "inventory"), days
        )
        values["dpo"], meta["dpo"] = dso(
            q.value("cost_of_revenue"),
            q.value("accounts_payable"),
            val(previous, "accounts_payable"),
            days,
        )
        ds, inv, dp = (values[k] for k in ("dso", "inventory_days", "dpo"))
        values["cash_conversion_cycle"] = (
            ds + inv - dp if ds is not None and inv is not None and dp is not None else None
        )
    else:
        for name in ("dso", "inventory_days", "dpo", "cash_conversion_cycle"):
            values[name] = None
        meta["days_metrics"] = "Exact period_start unavailable"

    def gt(name: str, threshold: Decimal) -> bool:
        value = values.get(name)
        return value is not None and value > threshold

    def lt(name: str, threshold: Decimal) -> bool:
        value = values.get(name)
        return value is not None and value < threshold

    flags = []
    if gt("revenue_yoy", D(".20")) and lt("fcf_yoy", D(0)):
        flags.append("revenue_fcf_divergence")
    rev = values.get("revenue_yoy")
    for metric in ("accounts_receivable", "inventory"):
        if rev is not None and gt(metric + "_yoy", rev + D(".20")):
            flags.append("revenue_" + metric + "_divergence")
    if gt("eps_yoy", D(".20")) and lt("fcf_yoy", D(0)):
        flags.append("eps_cash_flow_divergence")
    meta["anomaly_rule_version"] = (
        "diagnostics-1.0; growth 20%, AR/inventory gap 20 percentage points; no trading rules"
    )
    return FeatureSet(values, meta, tuple(flags))


def split_epoch(day) -> int:  # type: ignore[no-untyped-def]
    # Conservative discontinuity guards, NOT split-adjusted data. See sources in DECISIONS.
    from datetime import date

    return int(day >= date(2021, 7, 20)) + int(day >= date(2024, 6, 10))


def persist(db: Session, snapshot: QuarterlySnapshot, features: FeatureSet) -> None:
    for name, value in features.values.items():
        if db.scalar(
            select(QuantFeature.id).where(
                QuantFeature.source_snapshot_id == snapshot.id,
                QuantFeature.feature_name == name,
                QuantFeature.feature_version == VERSION,
            )
        ):
            continue
        db.add(
            QuantFeature(
                company_id=snapshot.company_id,
                as_of_timestamp=snapshot.as_of_timestamp,
                fiscal_year=snapshot.fiscal_year,
                fiscal_quarter=snapshot.fiscal_quarter,
                feature_name=name,
                feature_value=value,
                feature_version=VERSION,
                source_snapshot_id=snapshot.id,
                metadata_json={**features.metadata, "anomalies": list(features.anomalies)},
            )
        )
