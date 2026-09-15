"""Chronological replay coordinator. No evaluation database is opened here."""

from sqlalchemy import select

from valuation_engine.db.schema import SourceDocument
from valuation_engine.hardening.availability import AvailabilityResolver
from valuation_engine.research.inputs import FinancialInputs, period_name
from valuation_engine.research.numbers import POLICY, canonical
from valuation_engine.research.service import MODELS, build_forecast, revisions, stored_periods
from valuation_engine.research.valuation import build_valuation
from valuation_engine.time import calculate_next_tradable_timestamp


def checkpoints(db, company_id, through):
    resolver = AvailabilityResolver(db)
    result = []
    for doc in db.scalars(
        select(SourceDocument).where(
            SourceDocument.company_id == company_id, SourceDocument.source_provider == "NVIDIA IR"
        )
    ):
        fy, fq = doc.metadata_json["fiscal_year"], doc.metadata_json["fiscal_quarter"]
        e = resolver.by_document.get(doc.id)
        if (
            e is None
            or e.information_available_at > through
            or not (2021, 1) <= (fy, fq) <= (2027, 2)
        ):
            continue
        boundary = e.information_available_at
        result.append(
            dict(
                quarter=period_name(fy, fq),
                issuer_release=boundary,
                first_tradable=calculate_next_tradable_timestamp(boundary),
                source_document_id=doc.id,
            )
        )
    return sorted(result, key=lambda r: r["issuer_release"])


def replay(db, through, models=("A", "B", "C"), progress=None):
    output = []
    for checkpoint in checkpoints(db, 1, through):
        for kind in ("issuer_release", "first_tradable"):
            at = checkpoint[kind]
            if at > through:
                continue
            data = FinancialInputs(db, 1, at)
            for model in models:
                run = build_forecast(db, 1, at, kind, model, data)
                rev = revisions(db, run)
                value = build_valuation(db, run) if kind == "first_tradable" else None
                output.append(
                    dict(
                        quarter=checkpoint["quarter"],
                        checkpoint=kind,
                        model=MODELS[model],
                        run_id=run.id,
                        run_key=run.identity_key,
                        as_of=at,
                        valuation_id=value.id if value else None,
                        periods=stored_periods(db, run.id),
                        revision=rev,
                    )
                )
        db.commit()
        if progress:
            progress(checkpoint["quarter"])
    return canonical(
        dict(model_version=POLICY["version"], classification=POLICY["classification"], runs=output)
    )
