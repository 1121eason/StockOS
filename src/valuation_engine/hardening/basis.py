from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import (
    CorporateAction,
    FinancialFact,
    MarketPrice,
    PriceBasis,
    SourceDocument,
)
from valuation_engine.db.store import digest
from valuation_engine.time import ET, aware


class SplitBasis:
    def __init__(self, db: Session, company_id: int):
        self.actions = list(
            db.scalars(
                select(CorporateAction)
                .where(
                    CorporateAction.company_id == company_id, CorporateAction.action_type == "split"
                )
                .order_by(CorporateAction.split_date)
            )
        )
        if len({a.split_date for a in self.actions}) != len(self.actions):
            raise ValueError("Conflicting corporate action versions need explicit resolution")

    def factor(self, start: date, end: date) -> Decimal:
        if end < start:
            return Decimal(1) / self.factor(end, start)
        value = Decimal(1)
        for action in self.actions:
            if start < action.split_date <= end:
                value *= action.ratio_numerator / action.ratio_denominator
        return value

    def per_share(self, value: Decimal, start: date, end: date) -> Decimal:
        return value / self.factor(start, end)

    def shares(self, value: Decimal, start: date, end: date) -> Decimal:
        return value * self.factor(start, end)


def fact_basis(db: Session, fact: FinancialFact) -> date | None:
    """Original release current-period basis, or SEC accession presentation vintage."""
    doc = db.get(SourceDocument, fact.source_document_id)
    assert doc is not None
    explicit = fact.metadata_json.get("share_basis_date")
    if explicit:
        return date.fromisoformat(explicit)
    if doc.source_provider == "NVIDIA IR" and doc.metadata_json.get("publication_date"):
        return date.fromisoformat(doc.metadata_json["publication_date"])
    # SEC comparatives can be retrospectively split-adjusted. Do not infer their basis
    # merely from the filing date; require a verified accession-specific declaration.
    return None


def build_price_bases(
    db: Session, company_id: int, verified_archive: tuple[int, list[int]] | None = None
) -> dict[str, int]:
    split = SplitBasis(db, company_id)
    made = skipped = 0
    archives = list(
        db.scalars(
            select(SourceDocument)
            .where(SourceDocument.document_type == "Original market data response")
            .order_by(SourceDocument.id.desc())
        )
    )
    for bar in db.scalars(select(MarketPrice).where(MarketPrice.company_id == company_id)):
        archive = next(
            (d for d in archives if bar.id in d.metadata_json.get("matched_market_price_ids", [])),
            None,
        )
        if verified_archive and bar.id in verified_archive[1]:
            archive = db.get(SourceDocument, verified_archive[0])
        key = digest(
            [
                bar.id,
                [a.identity_key for a in split.actions],
                archive.id if archive else None,
                "price-basis-1.1",
            ]
        )
        if db.scalar(select(PriceBasis.id).where(PriceBasis.identity_key == key)):
            skipped += 1
            continue
        anchor = bar.retrieved_at.astimezone(ET).date()
        day = bar.timestamp.astimezone(ET).date()
        factor = split.factor(day, anchor)
        supplied_raw = bar.price_type == "daily_unadjusted"
        if not supplied_raw and bar.price_type != "daily_split_adjusted_current_vintage":
            raise ValueError("Unsupported vendor price basis")
        raw = {
            name: getattr(bar, name) if supplied_raw else getattr(bar, name) * factor
            for name in ("open", "high", "low", "close")
        }
        comparable = {name: raw[name] / factor for name in raw}
        db.add(
            PriceBasis(
                identity_key=key,
                market_price_id=bar.id,
                source_document_id=archive.id if archive else None,
                **{"raw_" + k: v for k, v in raw.items()},
                **{"split_adjusted_" + k: v for k, v in comparable.items()},
                raw_origin="provider_as_traded" if supplied_raw else "research_reconstructed",
                adjusted_close=bar.adjusted_close,
                adjusted_open=None,
                adjusted_high=None,
                adjusted_low=None,
                split_factor=factor,
                total_adjustment_factor=bar.adjusted_close / raw["close"]
                if bar.adjusted_close
                else None,
                basis_date=anchor,
                metadata_json={
                    "source_document_id": archive.id if archive else None,
                    "original_response_hash": archive.content_hash if archive else None,
                    "provider": bar.provider,
                    "retrieved_at": bar.retrieved_at.isoformat(),
                    "source_bar_hash": bar.content_hash,
                    "corporate_action_ids": [
                        a.id for a in split.actions if day < a.split_date <= anchor
                    ],
                    "formula": "as_traded = vendor_split_adjusted * subsequent_split_share_factors",
                    "vendor_raw_observed": supplied_raw,
                    "limitation": None
                    if supplied_raw
                    else "Reconstructed from vendor current-vintage split-adjusted OHLC; not independently observed raw prices",
                    "adjusted_ohlc_policy": "Only adjusted close supplied; other total-return adjusted fields remain null",
                },
            )
        )
        made += 1
    db.flush()
    return {"created": made, "skipped": skipped}


def get_price_as_reported(
    db: Session,
    company_id: int,
    as_of: datetime,
    field: str = "open",
    *,
    require_observed: bool = False,
) -> dict[str, Any] | None:
    """Get last observable field; daily high/low/close are never visible at open."""
    if field not in ("open", "high", "low", "close"):
        raise ValueError("Unsupported OHLC field")
    at = aware(as_of)
    clock = MarketPrice.timestamp if field == "open" else MarketPrice.available_at
    rows = db.execute(
        select(MarketPrice, PriceBasis)
        .join(PriceBasis, PriceBasis.market_price_id == MarketPrice.id)
        .where(MarketPrice.company_id == company_id, clock <= at)
        .order_by(clock.desc(), MarketPrice.retrieved_at.desc(), PriceBasis.id.desc())
    )
    for bar, basis in rows:
        if require_observed and (basis.raw_origin != "provider_as_traded" or bar.retrieved_at > at):
            continue
        return {
            "value": getattr(basis, "raw_" + field),
            "basis": "as_traded",
            "field": field,
            "basis_date": bar.timestamp.astimezone(ET).date(),
            "origin": basis.raw_origin,
            "market_price_id": bar.id,
            "price_basis_id": basis.id,
            "available_at": bar.timestamp if field == "open" else bar.available_at,
            "retrieved_at": bar.retrieved_at,
            "provider": bar.provider,
            "provenance": basis.metadata_json,
            "snapshot_kind": "research_reconstruction"
            if bar.retrieved_at > at
            else "contemporaneously_stored",
        }
    return None


def get_split_adjusted_price(
    db: Session, company_id: int, as_of: datetime, basis_date: date, field: str = "open"
) -> dict[str, Any] | None:
    quote = get_price_as_reported(db, company_id, as_of, field)
    if quote is None:
        return None
    split = SplitBasis(db, company_id)
    quote["split_factor"] = split.factor(quote["basis_date"], basis_date)
    quote["value"] = split.per_share(quote["value"], quote["basis_date"], basis_date)
    quote.update(basis="split_comparable", basis_date=basis_date)
    return quote
