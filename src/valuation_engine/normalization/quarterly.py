from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.calendar_math import prior_period as prior_period
from valuation_engine.db.schema import FinancialFact, QuarterlySnapshot
from valuation_engine.db.store import digest
from valuation_engine.hardening.availability import AvailabilityResolver
from valuation_engine.hardening.basis import fact_basis
from valuation_engine.normalization.mapping import CONCEPTS, INSTANT, NON_ADDITIVE, VERSION
from valuation_engine.time import aware, calculate_next_tradable_timestamp


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True)
    value: Decimal
    unit: str
    fact_ids: tuple[int, ...]
    available_at: datetime
    formula: str
    metadata: dict[str, Any] = {}

    @field_validator("available_at")
    @classmethod
    def timezone(cls, v: datetime) -> datetime:
        return aware(v)


class Quarter(BaseModel):
    model_config = ConfigDict(frozen=True)
    company_id: int
    fiscal_year: int
    fiscal_quarter: int
    as_of: datetime
    period_start: date | None
    period_end: date
    metrics: dict[str, Observation]
    missing: list[str]
    selection_policy: str

    def value(self, metric: str) -> Decimal | None:
        obs = self.metrics.get(metric)
        return obs.value if obs else None


class PointInTimeRepository:
    """Financial-fact allowlist only. Never accepts free-form table/feature names."""

    def __init__(self, db: Session, company_id: int, *, source_document_ids=None):
        self._db = db
        self.company_id = company_id
        self.source_document_ids = source_document_ids

    def normalize_eps(self, observation: Observation, basis_date: date) -> Decimal | None:
        from valuation_engine.hardening.basis import SplitBasis

        start = observation.metadata.get("share_basis_date")
        if not start:
            return None
        return SplitBasis(self._db, self.company_id).per_share(
            observation.value, date.fromisoformat(start), basis_date
        )

    def quarter(
        self,
        fy: int,
        fq: int,
        as_of: datetime,
        policy: Literal["originally_reported", "latest_restated"] = "originally_reported",
    ) -> Quarter | None:
        as_of = aware(as_of)
        if policy not in ("originally_reported", "latest_restated"):
            raise ValueError("Invalid PIT selection policy")
        resolver = AvailabilityResolver(self._db)
        facts = list(
            self._db.scalars(
                select(FinancialFact).where(
                    FinancialFact.company_id == self.company_id,
                    FinancialFact.fiscal_year == fy,
                    FinancialFact.fiscal_quarter == fq,
                )
            ).all()
        )
        facts = [
            f
            for f in facts
            if resolver.time(f) <= as_of
            and (
                self.source_document_ids is None or f.source_document_id in self.source_document_ids
            )
        ]
        if not facts:
            return None

        def pick(rows: list[FinancialFact]) -> FinancialFact | None:
            if not rows:
                return None
            rows.sort(
                key=lambda f: (
                    resolver.time(f)
                    if policy == "originally_reported"
                    else -resolver.time(f).timestamp(),
                    f.source_priority,
                    f.id,
                )
            )
            first = rows[0]
            peers = [
                x
                for x in rows
                if resolver.time(x) == resolver.time(first)
                and x.source_priority == first.source_priority
            ]
            return first if len({x.value for x in peers}) == 1 else None

        metrics: dict[str, Observation] = {}
        for metric in sorted({x.metric_name for x in facts}):
            eligible = [x for x in facts if x.metric_name == metric]
            direct = pick([x for x in eligible if x.duration_kind in ("quarter", "instant")])
            if direct:
                metrics[metric] = Observation(
                    value=direct.value,
                    unit=direct.unit,
                    fact_ids=(direct.id,),
                    available_at=resolver.time(direct),
                    formula="reported",
                    metadata={
                        **direct.metadata_json,
                        **resolver.metadata(direct),
                        "source_document_id": direct.source_document_id,
                        "share_basis_date": str(fact_basis(self._db, direct))
                        if fact_basis(self._db, direct)
                        else None,
                    },
                )
            if metric in NON_ADDITIVE or metric in INSTANT:
                continue
            current = pick([x for x in eligible if x.duration_kind in ("ytd", "annual")])
            if not current or not current.period_start or fq == 1:
                continue
            previous = list(
                self._db.scalars(
                    select(FinancialFact).where(
                        FinancialFact.company_id == self.company_id,
                        FinancialFact.fiscal_year == fy,
                        FinancialFact.fiscal_quarter == fq - 1,
                        FinancialFact.metric_name == metric,
                        FinancialFact.unit == current.unit,
                        FinancialFact.taxonomy_name == current.taxonomy_name,
                        FinancialFact.period_start == current.period_start,
                        FinancialFact.duration_kind.in_(("quarter", "ytd")),
                    )
                ).all()
            )
            previous = [
                f
                for f in previous
                if resolver.time(f) <= as_of
                and (
                    self.source_document_ids is None
                    or f.source_document_id in self.source_document_ids
                )
            ]
            # Prefer comparative YTD from SAME accession; otherwise selected PIT vintage.
            matching = [x for x in previous if x.source_document_id == current.source_document_id]
            prior = pick(matching or previous)
            if prior and 75 <= (current.period_end - prior.period_end).days <= 105:
                derived_availability = max(resolver.time(current), resolver.time(prior))
                if direct and (
                    (
                        policy == "originally_reported"
                        and resolver.time(direct) <= derived_availability
                    )
                    or (
                        policy == "latest_restated"
                        and resolver.time(direct) >= derived_availability
                    )
                ):
                    continue
                metrics[metric] = Observation(
                    value=current.value - prior.value,
                    unit=current.unit,
                    fact_ids=(current.id, prior.id),
                    available_at=derived_availability,
                    formula="current_ytd_minus_previous_ytd",
                    metadata={
                        "formula_version": VERSION,
                        "mixed_vintage": current.source_document_id != prior.source_document_id,
                        "period_start": str(prior.period_end + timedelta(days=1)),
                    },
                )

        def derived(name: str, left: str, right: str, subtract: bool) -> None:
            if name in metrics or left not in metrics or right not in metrics:
                return
            a, b = metrics[left], metrics[right]
            metrics[name] = Observation(
                value=a.value - b.value if subtract else a.value + b.value,
                unit=a.unit,
                fact_ids=a.fact_ids + b.fact_ids,
                available_at=max(a.available_at, b.available_at),
                formula=f"{left} {'-' if subtract else '+'} {right}",
                metadata={"formula_version": VERSION},
            )

        derived("fcf", "ocf", "capex", True)
        derived("debt", "debt_current", "debt_noncurrent", False)
        derived("gross_profit", "revenue", "cost_of_revenue", True)
        # FY27 securities presentation changed; retain component provenance.
        derived(
            "marketable_securities",
            "marketable_debt_securities",
            "marketable_equity_securities",
            False,
        )
        # The release's combined liquid assets and cash-flow ending cash describe
        # the same balance-sheet date; retain both source fact IDs in the subtraction.
        derived("marketable_securities", "cash_and_marketable_securities", "cash", True)
        ends = [x.period_end for x in facts if x.metric_name == "revenue"]
        end = max(ends) if ends else max(x.period_end for x in facts)
        starts = [
            x.period_start
            for x in facts
            if x.duration_kind == "quarter" and x.period_start and x.period_end == end
        ]
        start = min(starts) if starts else None
        if start is None:
            derived_starts = [
                x.metadata.get("period_start")
                for x in metrics.values()
                if x.metadata.get("period_start")
            ]
            start = date.fromisoformat(str(derived_starts[0])) if derived_starts else None
        return Quarter(
            company_id=self.company_id,
            fiscal_year=fy,
            fiscal_quarter=fq,
            as_of=as_of,
            period_start=start,
            period_end=end,
            metrics=metrics,
            missing=sorted((set(CONCEPTS) | {"fcf", "debt"}) - metrics.keys()),
            selection_policy=policy,
        )

    def save(self, quarter: Quarter) -> QuarterlySnapshot:
        data = quarter.model_dump(mode="json")
        key = digest([data, VERSION])
        existing = self._db.scalar(
            select(QuarterlySnapshot).where(QuarterlySnapshot.identity_key == key)
        )
        if existing:
            return existing
        available = max(x.available_at for x in quarter.metrics.values())
        row = QuarterlySnapshot(
            identity_key=key,
            company_id=self.company_id,
            fiscal_year=quarter.fiscal_year,
            fiscal_quarter=quarter.fiscal_quarter,
            as_of_timestamp=quarter.as_of,
            available_at=available,
            tradable_at=calculate_next_tradable_timestamp(available),
            model_version=VERSION,
            selection_policy=quarter.selection_policy,
            payload=data,
        )
        self._db.add(row)
        self._db.flush()
        return row
