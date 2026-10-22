"""Read-only financial/guidance boundary; never opens an evaluation database."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.calendar_math import period_name as period_name
from valuation_engine.calendar_math import period_tuple as period_tuple
from valuation_engine.db.schema import FinancialFact, GuidanceItem, SourceDocument
from valuation_engine.db.store import digest, read_document
from valuation_engine.hardening.availability import AvailabilityResolver
from valuation_engine.hardening.basis import SplitBasis
from valuation_engine.ingestion.ir import parse_release
from valuation_engine.normalization.quarterly import PointInTimeRepository, Quarter, prior_period
from valuation_engine.research.numbers import POLICY, D, div
from valuation_engine.time import ET, aware, calculate_next_tradable_timestamp


class FinancialInputs:
    def __init__(self, db: Session, company_id: int, at: datetime, anchor=None):
        self.db, self.company_id, self.at = db, company_id, aware(at)
        self.repo = PointInTimeRepository(db, company_id)
        self.resolver = AvailabilityResolver(db)
        self.guidance_resolver = AvailabilityResolver(db, "guidance")
        self._quarters: dict[tuple[int, int], Quarter | None] = {}
        self.inputs: dict[str, Any] = {}
        self.warnings: list[dict[str, Any]] = []
        self.split = SplitBasis(db, company_id)
        # A future split is never a forecast input; everything stays on the current as-traded basis.
        self.split.actions = [
            a
            for a in self.split.actions
            if a.announced_at <= self.at and a.split_date <= self.at.astimezone(ET).date()
        ]
        self.basis_date = self.at.astimezone(ET).date()
        if anchor is None:
            eligible = self.releases()
            if not eligible:
                raise ValueError("No issuer financial release eligible at information cutoff")
            anchor = max(eligible, key=lambda x: x[0])[0]
        self.anchor = anchor
        self.current = self.quarter(*anchor)
        if self.current is None or self.current.value("revenue") is None:
            raise ValueError("No eligible revenue for forecast anchor")
        self.history = [
            self.quarter(*prior_period(anchor[0], anchor[1], n))
            for n in range(POLICY["history_quarters"])
        ]
        self.guidance = self.eligible_guidance()

    def releases(self):
        result = []
        for doc in self.db.scalars(
            select(SourceDocument).where(
                SourceDocument.company_id == self.company_id,
                SourceDocument.source_provider == "NVIDIA IR",
            )
        ):
            e = self.resolver.by_document.get(doc.id)
            if e and e.information_available_at <= self.at:
                result.append(
                    (
                        (doc.metadata_json["fiscal_year"], doc.metadata_json["fiscal_quarter"]),
                        e.information_available_at,
                        doc.id,
                    )
                )
        return result

    def quarter(self, fy, fq):
        if (fy, fq) not in self._quarters:
            self._quarters[fy, fq] = self.repo.quarter(fy, fq, self.at)
        return self._quarters[fy, fq]

    def value(self, quarter, metric):
        if quarter is None or metric not in quarter.metrics:
            return None
        obs = quarter.metrics[metric]
        if obs.available_at > self.at:
            raise ValueError("Future financial input rejected")
        key = period_name(quarter.fiscal_year, quarter.fiscal_quarter) + ":" + metric
        entry = obs.model_dump(mode="json")
        value = obs.value
        if metric in ("eps_diluted", "diluted_shares"):
            basis = obs.metadata.get("share_basis_date")
            if not basis:
                self.warnings.append({"parameter": key, "reason": "unverified_share_basis"})
                return None
            factor = self.split.factor(date.fromisoformat(basis), self.basis_date)
            value = value / factor if metric == "eps_diluted" else value * factor
            entry["normalization"] = {
                "original_basis": basis,
                "basis_date": str(self.basis_date),
                "factor": str(factor),
            }
        self.inputs[key] = entry
        return value

    def eligible_guidance(self):
        rows = [
            g
            for g in self.db.scalars(
                select(GuidanceItem).where(
                    GuidanceItem.company_id == self.company_id, GuidanceItem.basis == "GAAP"
                )
            )
            if self.guidance_resolver.time(g) <= self.at
        ]
        valid: dict[int, set[str] | None] = {}
        for g in rows:
            if g.source_document_id not in valid:
                doc = self.db.get(SourceDocument, g.source_document_id)
                assert doc is not None
                if doc.source_provider == "NVIDIA IR":
                    parsed = parse_release(
                        read_document(
                            doc,
                            self.db.info.get("research_raw_dir"),
                            strict_root="research_raw_dir" in self.db.info,
                        ),
                        doc.metadata_json["fiscal_year"],
                        doc.metadata_json["fiscal_quarter"],
                    )
                    valid[g.source_document_id] = {
                        digest([doc.id, item]) for item in parsed["guidance"]
                    }
                else:
                    valid[g.source_document_id] = (
                        None  # Explicit synthetic/test or structured guidance.
                    )
        return [
            g
            for g in rows
            if valid[g.source_document_id] is None
            or g.identity_key in (valid[g.source_document_id] or set())
        ]

    def guidance_for(self, fy, fq):
        candidates = [
            g
            for g in self.guidance
            if g.guidance_for_period == period_name(fy, fq)
            or (g.metric_name == "tax_rate" and g.guidance_for_period == f"FY{fy}")
        ]
        result: dict[str, GuidanceItem] = {}
        for g in sorted(
            candidates, key=lambda g: (self.guidance_resolver.time(g), g.id), reverse=True
        ):
            result.setdefault(g.metric_name, g)
        return result

    def guidance_record(self, g):
        doc = self.db.get(SourceDocument, g.source_document_id)
        assert doc is not None
        return dict(
            id=g.id,
            midpoint=g.mid_value,
            low=g.low_value,
            high=g.high_value,
            basis=g.basis,
            target=g.guidance_for_period,
            available_at=self.guidance_resolver.time(g),
            source_document_id=g.source_document_id,
            source_url=doc.source_url,
            source_hash=doc.content_hash,
        )

    def observed_metric(self, q, metric):
        if metric == "gross_margin":
            return div(self.value(q, "gross_profit"), self.value(q, "revenue"))
        return self.value(q, metric)

    def guidance_accuracy(self):
        samples: dict[str, list[dict[str, Any]]] = {
            metric: [] for metric in ("revenue", "gross_margin", "operating_expenses")
        }
        for g in sorted(self.guidance, key=lambda g: (g.fiscal_year, g.fiscal_quarter, g.id)):
            if (
                g.metric_name not in samples
                or "-Q" not in g.guidance_for_period
                or g.mid_value is None
            ):
                continue
            fy, fq = period_tuple(g.guidance_for_period)
            if (fy, fq) > self.anchor:
                continue
            q = self.quarter(fy, fq)
            actual = self.observed_metric(q, g.metric_name)
            keys = (
                ("gross_profit", "revenue") if g.metric_name == "gross_margin" else (g.metric_name,)
            )
            available = max(
                (q.metrics[k].available_at for k in keys if q and k in q.metrics), default=None
            )
            if (
                actual is None
                or available is None
                or not self.guidance_resolver.time(g) < available <= self.at
            ):
                continue
            error = (
                actual - g.mid_value
                if g.metric_name == "gross_margin"
                else div(actual, g.mid_value)
            )
            if error is None:
                continue
            if g.metric_name != "gross_margin":
                error -= D(1)
            samples[g.metric_name].append(
                {
                    "target": g.guidance_for_period,
                    "guidance": self.guidance_record(g),
                    "actual": actual,
                    "actual_available_at": available,
                    "surprise": error,
                    "actual_fact_ids": sorted({i for k in keys for i in q.metrics[k].fact_ids}),
                }
            )
        # One comparable guidance observation per target; latest eligible guidance precedes actual.
        for metric, values in samples.items():
            distinct: dict[str, Any] = {}
            for sample in values:
                target = sample["target"]
                if (
                    target not in distinct
                    or sample["guidance"]["available_at"]
                    > distinct[target]["guidance"]["available_at"]
                ):
                    distinct[target] = sample
            samples[metric] = sorted(distinct.values(), key=lambda x: period_tuple(x["target"]))
        return samples

    @property
    def tradable_at(self):
        return calculate_next_tradable_timestamp(self.current.metrics["revenue"].available_at)

    def provenance(self):
        ids = sorted({i for o in self.inputs.values() for i in o["fact_ids"]})
        sources = {}
        for fact in self.db.scalars(select(FinancialFact).where(FinancialFact.id.in_(ids))):
            doc = self.db.get(SourceDocument, fact.source_document_id)
            assert doc is not None
            sources[str(fact.id)] = dict(
                source_document_id=doc.id,
                source_hash=doc.content_hash,
                source_url=doc.source_url,
                taxonomy=fact.taxonomy_name,
            )
        return {
            "observations": self.inputs,
            "fact_sources": sources,
            "basis_date": self.basis_date,
            "corporate_actions": [a.id for a in self.split.actions],
        }
