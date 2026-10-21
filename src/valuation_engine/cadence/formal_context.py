"""Read one exact immutable forecast/valuation/corrected-Regime cohort, without replay."""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import (
    AssumptionSet,
    Company,
    ForecastRun,
    RegimeSnapshot,
    ResearchValuation,
)
from valuation_engine.db.store import digest
from valuation_engine.decision.signal_fusion import validate_formal_regime
from valuation_engine.quant.ai_context import resolve_run
from valuation_engine.regime.confidence import POLICY as CORRECTED_POLICY
from valuation_engine.regime.confidence import snapshot_contract
from valuation_engine.regime.service import payload
from valuation_engine.research.numbers import POLICY
from valuation_engine.time import aware


@dataclass(frozen=True)
class FormalCadenceContext:
    valuation_id: int
    dcf_base: Any
    metadata_json: Any
    regime: dict[str, Any]


def _checkpoint(value: str | datetime) -> datetime:
    if not isinstance(value, (str, datetime)):
        raise ValueError("checkpoint_timestamp must be a timezone-aware timestamp")
    return aware(datetime.fromisoformat(value) if isinstance(value, str) else value)


def _resolve(db: Session, company_id: int, quarter: str, day: date, checkpoint: datetime | None):
    if checkpoint is not None:
        run = resolve_run(db, company_id, quarter, cutoff=checkpoint)
        if run.forecast_as_of != checkpoint:
            raise ValueError("No exact formal forecast at the requested checkpoint")
        return run

    # Discover stored checkpoints, never invent an end-of-day cutoff. Eligibility
    # is checked separately at each instant, using the existing formal resolver.
    candidates = {
        aware(row.forecast_as_of)
        for row in db.scalars(select(ForecastRun).where(ForecastRun.company_id == company_id))
        if row.metadata_json.get("anchor") == quarter and aware(row.forecast_as_of).date() == day
    }
    eligible = []
    for candidate in sorted(candidates):
        try:
            run = resolve_run(db, company_id, quarter, cutoff=candidate)
        except ValueError as exc:
            if str(exc).startswith("No eligible immutable formal Quant forecast"):
                continue
            raise
        if run.forecast_as_of == candidate:
            eligible.append(run)
    if len(eligible) != 1:
        raise ValueError(
            "Expected exactly one eligible formal checkpoint on the requested UTC date"
        )
    return eligible[0]


def load_formal_context(
    path: Path,
    ticker: str,
    quarter: str,
    as_of_date: str,
    checkpoint_timestamp: str | datetime | None = None,
) -> FormalCadenceContext:
    day = date.fromisoformat(as_of_date)
    checkpoint = _checkpoint(checkpoint_timestamp) if checkpoint_timestamp is not None else None
    if checkpoint is not None and checkpoint.date() != day:
        raise ValueError("checkpoint_timestamp must match as_of_date on the UTC date")
    uri = path.resolve().as_uri() + "?mode=ro"
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    try:
        with Session(engine, autoflush=False) as db:
            company = db.scalar(select(Company).where(Company.ticker == ticker))
            if company is None:
                raise ValueError(f"No formal company found for ticker {ticker}")
            run = _resolve(db, company.id, quarter, day, checkpoint)
            valuations = list(
                db.scalars(
                    select(ResearchValuation.id).where(
                        ResearchValuation.company_id == company.id,
                        ResearchValuation.forecast_run_id == run.id,
                        ResearchValuation.as_of_timestamp == run.forecast_as_of,
                        ResearchValuation.valuation_model_version == POLICY["valuation_version"],
                    )
                )
            )
            if not valuations:
                raise ValueError("No quantitative valuation found for the exact formal checkpoint")
            if len(valuations) != 1:
                raise ValueError(
                    "Ambiguous quantitative valuations for the exact formal checkpoint"
                )
            # Keep the existing cadence numeric/JSON input guards, including malformed
            # storage values, rather than coercing them through ORM Numeric/JSON types.
            valuation = (
                db.connection()
                .exec_driver_sql(
                    "SELECT dcf_base, metadata_json FROM research_valuations WHERE id = ?",
                    (valuations[0],),
                )
                .one()
            )
            assumption_hash = digest(payload(CORRECTED_POLICY))
            snapshots = list(
                db.scalars(
                    select(RegimeSnapshot)
                    .join(AssumptionSet)
                    .where(
                        RegimeSnapshot.company_id == company.id,
                        RegimeSnapshot.forecast_run_id == run.id,
                        RegimeSnapshot.input_snapshot_id == run.input_snapshot_id,
                        RegimeSnapshot.as_of_timestamp == run.forecast_as_of,
                        RegimeSnapshot.policy_version == CORRECTED_POLICY["version"],
                        AssumptionSet.content_hash == assumption_hash,
                    )
                )
            )
            if len(snapshots) != 1:
                raise ValueError(
                    "Expected exactly one corrected Regime snapshot for the formal checkpoint"
                )
            row = snapshots[0]
            try:
                envelope = snapshot_contract(row)
                metadata = row.metadata_json
                if metadata is None or metadata["assumption_hash"] != assumption_hash:
                    raise ValueError("Regime assumption hash does not match the corrected policy")
                if (
                    row.model_version != CORRECTED_POLICY["version"]
                    or envelope["policy_version"] != CORRECTED_POLICY["version"]
                    or envelope["forecast_run_id"] != run.id
                    or envelope["quarter"] != run.metadata_json["anchor"]
                    or envelope["quarter"] != quarter
                    or _checkpoint(envelope["as_of"]) != run.information_cutoff
                ):
                    raise ValueError("Regime envelope does not match the formal forecast identity")
                envelope.update(
                    company_id=company.id,
                    input_snapshot_id=run.input_snapshot_id,
                    checkpoint_timestamp=aware(run.forecast_as_of).isoformat(),
                    assumption_hash=assumption_hash,
                    input_lineage=metadata["inputs"],
                    stress_dimensions=metadata["state"]["stress_dimensions"],
                )
                regime = validate_formal_regime(envelope)
            except (KeyError, TypeError, ArithmeticError, AttributeError) as exc:
                raise ValueError("Invalid or incomplete corrected Regime envelope") from exc
            return FormalCadenceContext(valuations[0], valuation[0], valuation[1], regime)
    finally:
        engine.dispose()
