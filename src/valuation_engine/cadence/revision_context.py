"""Read an explicitly selected same-fiscal-target revision without rebuilding forecasts."""

import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from valuation_engine.cadence.formal_context import FormalCadenceContext
from valuation_engine.db.schema import ForecastRevision, ForecastRun
from valuation_engine.db.store import digest
from valuation_engine.decision.signal_fusion import ForecastRevisionInput
from valuation_engine.time import aware


@dataclass(frozen=True)
class CadenceRevisionContext:
    signal: ForecastRevisionInput | None
    receipt: dict[str, Any]


def _number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"Revision {field} must be a finite number or null")
    try:
        result = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"Revision {field} must be a finite number or null") from exc
    if not math.isfinite(result):
        raise ValueError(f"Revision {field} must be a finite number or null")
    return result


def load_revision_context(
    path: Path, formal: FormalCadenceContext, target: str | None
) -> CadenceRevisionContext:
    """No default horizon, cross-run fallback, metric cloning, or zero imputation."""
    receipt: dict[str, Any] = {
        "status": "UNAVAILABLE",
        "reason": "fiscal_target_not_selected",
        "company_id": formal.regime["company_id"],
        "forecast_run_id": formal.regime["forecast_run_id"],
        "checkpoint_timestamp": formal.regime["checkpoint_timestamp"],
        "target": target,
        "revision_id": None,
        "previous_run_id": None,
        "metrics": None,
    }
    if target is None:
        return CadenceRevisionContext(None, receipt)
    if not isinstance(target, str) or re.fullmatch(r"FY[0-9]{4}(?:-Q[1-4])?", target) is None:
        raise ValueError("revision_target must be an explicit fiscal target: FY2027 or FY2027-Q3")
    uri = path.resolve().as_uri() + "?mode=ro"
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    try:
        with Session(engine, autoflush=False) as db:
            run = db.get(ForecastRun, receipt["forecast_run_id"])
            if (
                run is None
                or run.company_id != receipt["company_id"]
                or (aware(run.forecast_as_of).isoformat() != receipt["checkpoint_timestamp"])
            ):
                raise ValueError("Revision current run does not match the formal checkpoint")
            rows = list(
                db.scalars(
                    select(ForecastRevision).where(ForecastRevision.forecast_run_id == run.id)
                )
            )
            if not rows:
                receipt["reason"] = "exact_run_revision_not_stored"
                return CadenceRevisionContext(None, receipt)
            if len(rows) != 1:
                raise ValueError("Ambiguous revisions for the exact formal forecast")
            row = rows[0]
            # Use the producer's same-model, same-policy, strictly earlier predecessor rule.
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
            if (
                previous is None
                or row.previous_run_id != previous.id
                or (
                    aware(previous.information_cutoff) > aware(run.information_cutoff)
                    or aware(previous.information_cutoff) > aware(previous.forecast_as_of)
                    or row.identity_key
                    != digest([previous.identity_key, run.identity_key, "ForecastRevisionV1"])
                )
            ):
                raise ValueError(
                    "Revision predecessor or identity does not match the formal cohort"
                )
            metadata = row.metadata_json
            if not isinstance(metadata, dict) or metadata.get("status") != "available":
                raise ValueError("Revision metadata must be an available producer object")
            for field, expected in (("previous_run_id", previous.id), ("forecast_run_id", run.id)):
                if type(metadata.get(field)) is not int or metadata[field] != expected:
                    raise ValueError("Revision payload identity does not match its stored row")
            factor = _number(metadata.get("split_factor"), "split_factor")
            if factor is None or factor <= 0:
                raise ValueError("Revision split_factor must be positive")
            comparisons = metadata.get("comparisons")
            if not isinstance(comparisons, list) or not all(
                isinstance(c, dict) for c in comparisons
            ):
                raise ValueError("Revision comparisons must be a list of producer objects")
            receipt.update(
                revision_id=row.id,
                previous_run_id=previous.id,
                previous_checkpoint_timestamp=aware(previous.forecast_as_of).isoformat(),
                split_factor=factor,
            )
            selected = [c for c in comparisons if c.get("target") == target]
            if not selected:
                receipt["reason"] = "selected_fiscal_target_not_available"
                return CadenceRevisionContext(None, receipt)
            if len(selected) != 1:
                raise ValueError("Ambiguous comparisons for the selected fiscal target")
            comparison = selected[0]
            labels = {"quarter"} if "-Q" in target else {"FY1", "FY2"}
            if any(
                not isinstance(comparison.get(key), str) or comparison[key] not in labels
                for key in ("previous_label", "new_label")
            ):
                raise ValueError("Revision labels do not describe the selected fiscal target")
            raw_metrics = comparison.get("metrics")
            if not isinstance(raw_metrics, dict):
                raise ValueError("Revision metrics must be an object")
            metrics = {}
            for name in ("revenue", "eps", "free_cash_flow"):
                metric = raw_metrics.get(name)
                if not isinstance(metric, dict) or "percentage_revision" not in metric:
                    raise ValueError(f"Revision metric is missing: {name}")
                metrics[name] = _number(metric["percentage_revision"], name)
            receipt.update(
                metrics=metrics,
                previous_label=comparison["previous_label"],
                new_label=comparison["new_label"],
                reason=None,
            )
            if any(value is None for value in metrics.values()):
                receipt.update(status="INCOMPLETE", reason="missing_revision_metrics")
                return CadenceRevisionContext(None, receipt)
            revenue, eps, fcf = (metrics[k] for k in ("revenue", "eps", "free_cash_flow"))
            assert revenue is not None and eps is not None and fcf is not None
            # Preserve the existing cadence upward label and fusion downside boundary.
            direction = "DOWNWARD" if revenue < -0.03 else "UPWARD" if revenue > 0.05 else "NEUTRAL"
            receipt["status"] = "AVAILABLE"
            return CadenceRevisionContext(
                ForecastRevisionInput(revenue, eps, fcf, direction), receipt
            )
    finally:
        engine.dispose()
