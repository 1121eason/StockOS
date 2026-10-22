"""PIT shares outstanding; weighted-average income-statement denominators are excluded."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from bs4 import BeautifulSoup, Tag
from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import Filing, ShareCountObservation, SourceDocument
from valuation_engine.db.store import digest, read_document
from valuation_engine.hardening.basis import SplitBasis
from valuation_engine.time import ET, aware

VERSION = "pit-shares-1.1-closure"
PRIORITY = {"sec_cover": 1, "sec_structured": 2, "official_disclosure": 3}


def add_share_observation(
    db: Session,
    *,
    source: SourceDocument,
    share_count: Decimal,
    shares_as_of_date: date,
    published_at: datetime,
    available_at: datetime,
    source_type: str,
    basis_date: date,
    taxonomy_concept: str | None = None,
    share_class: str = "common",
    confidence: str = "high",
    metadata: dict[str, Any] | None = None,
) -> tuple[ShareCountObservation, bool]:
    count = Decimal(share_count)
    published, available = aware(published_at), aware(available_at)
    if source_type not in PRIORITY or share_class != "common":
        raise ValueError("Unsupported share source or class; do not aggregate unknown classes")
    if not count.is_finite() or count <= 0:
        raise ValueError("Shares outstanding must be a positive finite Decimal")
    if shares_as_of_date > published.astimezone(ET).date() or available < published:
        raise ValueError("Invalid share publication/as-of chronology")
    if taxonomy_concept and "WeightedAverage" in taxonomy_concept:
        raise ValueError("Weighted-average shares are not shares outstanding")
    # A changed archive version cannot be silently assigned its predecessor's publication clock.
    if source.metadata_json.get("changed_content"):
        available = max(available, source.retrieved_at)
    basis = {"kind": "as_reported", "basis_date": str(basis_date), "unit": "shares"}
    data = dict(
        company_id=source.company_id,
        share_class=share_class,
        share_count=count,
        shares_as_of_date=shares_as_of_date,
        published_at=published,
        available_at=available,
        source_document_id=source.id,
        source_type=source_type,
        taxonomy_concept=taxonomy_concept,
        split_basis=basis,
        normalized_share_count=count,
        normalized_basis_date=basis_date,
        confidence=confidence,
        metadata_json={
            **(metadata or {}),
            "version": VERSION,
            "normalization": "Absolute shares on original basis; valuation/comparable bases resolved at query time",
            "source_hash": source.content_hash,
        },
    )
    key = digest([data, VERSION])
    old = db.scalar(select(ShareCountObservation).where(ShareCountObservation.identity_key == key))
    if old:
        return old, False
    row = ShareCountObservation(identity_key=key, **data)
    db.add(row)
    db.flush()
    return row, True


def get_latest_known_shares(
    db: Session,
    company_id: int,
    as_of_timestamp: datetime,
    *,
    basis_date: date | None = None,
) -> dict[str, Any] | None:
    at = aware(as_of_timestamp)
    target = basis_date or at.astimezone(ET).date()
    rows = list(
        db.scalars(
            select(ShareCountObservation).where(
                ShareCountObservation.company_id == company_id,
                ShareCountObservation.share_class == "common",
                ShareCountObservation.available_at <= at,
                ShareCountObservation.shares_as_of_date <= at.astimezone(ET).date(),
            )
        )
    )
    if not rows:
        return None
    # Freshness is economic date, then source priority on that date, then latest known revision.
    # A newly filed old comparative cannot replace a more recent share observation.
    rows.sort(
        key=lambda r: (
            -r.shares_as_of_date.toordinal(),
            PRIORITY[r.source_type],
            -r.available_at.timestamp(),
            r.id,
        )
    )
    chosen = rows[0]
    peers = [
        r
        for r in rows
        if r.shares_as_of_date == chosen.shares_as_of_date
        and PRIORITY[r.source_type] == PRIORITY[chosen.source_type]
        and r.available_at == chosen.available_at
    ]
    split = SplitBasis(db, company_id)
    values = {split.shares(r.share_count, r.normalized_basis_date, target) for r in peers}
    if len(values) != 1:
        return None  # Same-priority simultaneous conflict is unavailable, never an arbitrary ID.
    source = db.get(SourceDocument, chosen.source_document_id)
    assert source is not None
    factor = split.factor(chosen.normalized_basis_date, target)
    return {
        "observation_id": chosen.id,
        "share_count": values.pop(),
        "original_share_count": chosen.share_count,
        "shares_as_of_date": chosen.shares_as_of_date,
        "published_at": chosen.published_at,
        "available_at": chosen.available_at,
        "original_split_basis": chosen.split_basis,
        "basis_date": target,
        "basis": "valuation_date_as_traded" if basis_date is None else "explicit_comparable",
        "split_factor": factor,
        "share_class": chosen.share_class,
        "source_document_id": source.id,
        "source_url": source.source_url,
        "source_hash": source.content_hash,
        "source_type": chosen.source_type,
        "taxonomy_concept": chosen.taxonomy_concept,
        "confidence": chosen.confidence,
        "age_days": (at.astimezone(ET).date() - chosen.shares_as_of_date).days,
        "corporate_action_ids": [
            a.id
            for a in split.actions
            if min(chosen.normalized_basis_date, target)
            < a.split_date
            <= max(chosen.normalized_basis_date, target)
        ],
        "selection_policy": "latest eligible economic date; source priority; latest eligible revision; conflict => unavailable",
        "calculation_version": VERSION,
    }


def filing_availability(filing: Filing) -> tuple[datetime, datetime, dict[str, Any]]:
    published = filing.accepted_timestamp or datetime.combine(
        filing.filing_date + timedelta(days=1), datetime.min.time(), ET
    )
    available = published + timedelta(minutes=3) if filing.accepted_timestamp else published
    return (
        published,
        available,
        {
            "accepted_timestamp": str(filing.accepted_timestamp),
            "publication_is_proxy": True,
            "timestamp_precision": "inferred_acceptance_buffer"
            if filing.accepted_timestamp
            else "date_only",
            "policy": "accepted_plus_3m"
            if filing.accepted_timestamp
            else "date_only_next_midnight",
            "accession": filing.accession_number,
        },
    )


def cover_share_values(raw: bytes, cik: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Read only explicit DEI cover-page iXBRL tags with entity, instant and shares unit."""
    soup = BeautifulSoup(raw, "html.parser")
    nodes = [n for n in soup.find_all(True) if isinstance(n, Tag)]
    by_id = {str(n.get("id")): n for n in nodes if n.get("id")}

    def local(n: Tag) -> str:
        return n.name.lower().split(":")[-1]

    result, errors = [], []
    for node in nodes:
        if str(node.get("name", "")).lower() != "dei:entitycommonstocksharesoutstanding":
            continue
        try:
            context = by_id[str(node["contextref"])]
            children = [n for n in context.find_all(True) if isinstance(n, Tag)]
            instants = [n.get_text(strip=True) for n in children if local(n) == "instant"]
            identifiers = [n.get_text(strip=True) for n in children if local(n) == "identifier"]
            if len(instants) != 1 or len(identifiers) != 1 or int(identifiers[0]) != int(cik):
                raise ValueError("Cover shares require matching entity and one instant context")
            if any(local(n) in ("explicitmember", "typedmember") for n in children):
                raise ValueError("Dimensioned share class requires explicit class mapping")
            unit = by_id[str(node["unitref"])]
            measures = [
                n.get_text(strip=True).lower().split(":")[-1]
                for n in unit.find_all(True)
                if isinstance(n, Tag) and local(n) == "measure"
            ]
            if measures != ["shares"]:
                raise ValueError("Cover share unit is not unambiguous shares")
            fmt = str(node.get("format", "")).lower().split(":")[-1]
            if fmt not in ("", "num-dot-decimal", "numdotdecimal", "num-comma-dot"):
                raise ValueError("Unsupported iXBRL number transformation")
            if node.get("xsi:nil") == "true" or node.get("continuedat"):
                raise ValueError("Nil or continued share fact requires explicit resolution")
            text = (
                node.get_text("", strip=True).replace(",", "").replace("\xa0", "").replace(" ", "")
            )
            count = Decimal(text) * Decimal(10) ** int(str(node.get("scale", "0")))
            if node.get("sign") == "-":
                count = -count
            if not count.is_finite() or count <= 0:
                raise ValueError("Invalid share count")
            result.append(
                {
                    "share_count": count,
                    "shares_as_of_date": date.fromisoformat(instants[0]),
                    "context_id": str(node["contextref"]),
                    "raw_text": text,
                    "scale": str(node.get("scale", "0")),
                    "decimals": str(node.get("decimals", "")),
                }
            )
        except (KeyError, ValueError, ArithmeticError) as exc:
            errors.append(str(exc))
    return result, errors


def ingest_cover_shares(db: Session, company_id: int, cik: str = "0001045810") -> dict[str, Any]:
    created = skipped = 0
    errors: list[dict[str, Any]] = []
    docs = db.scalars(
        select(SourceDocument).where(
            SourceDocument.company_id == company_id,
            SourceDocument.document_type == "SEC primary filing",
        )
    )
    for doc in docs:
        filing = db.get(Filing, doc.filing_id)
        assert filing is not None
        values, failures = cover_share_values(read_document(doc), cik)
        published, available, meta = filing_availability(filing)
        for value in values:
            try:
                _, added = add_share_observation(
                    db,
                    source=doc,
                    share_count=value["share_count"],
                    shares_as_of_date=value["shares_as_of_date"],
                    published_at=published,
                    available_at=available,
                    source_type="sec_cover",
                    basis_date=value["shares_as_of_date"],
                    taxonomy_concept="dei:EntityCommonStockSharesOutstanding",
                    metadata={
                        **meta,
                        **{k: str(v) for k, v in value.items()},
                        "basis_evidence": "Current cover-page share instant, not a financial-statement comparative",
                    },
                )
                created += added
                skipped += not added
            except ValueError as exc:
                failures.append(str(exc))
        if not values and not failures:
            failures.append("No supported DEI cover-page share tag; manual source review required")
        errors.extend(
            {"document_id": doc.id, "accession": filing.accession_number, "reason": e}
            for e in failures
        )
    return {"created": created, "skipped": skipped, "unavailable": errors}


def ingest_structured_shares(
    db: Session,
    filing: Filing,
    source: SourceDocument,
    values: list[dict[str, Any]],
) -> dict[str, Any]:
    split = SplitBasis(db, filing.company_id)
    published, available, meta = filing_availability(filing)
    if source.metadata_json.get("product_observed_at"):
        available = max(
            available, datetime.fromisoformat(source.metadata_json["product_observed_at"])
        )
    made = skipped = 0
    rejected = []
    for item in values:
        if item["metric"] != "period_end_shares":
            continue
        obs, concept = item["obs"], item["concept"]
        end = date.fromisoformat(obs["end"])
        reliable = (
            item["taxonomy"] == "dei"
            and concept == "EntityCommonStockSharesOutstanding"
            and 0 <= (filing.filing_date - end).days <= 35
        ) or (
            item["taxonomy"] == "us-gaap"
            and concept == "CommonStockSharesOutstanding"
            and end == filing.period_end
            and split.factor(end, filing.filing_date) == 1
        )
        if obs.get("start") or not reliable:
            rejected.append(
                {
                    "concept": concept,
                    "end": str(end),
                    "reason": "Unverified current-share date or comparative split basis",
                }
            )
            continue
        _, added = add_share_observation(
            db,
            source=source,
            share_count=Decimal(str(obs["val"])),
            shares_as_of_date=end,
            published_at=published,
            available_at=available,
            source_type="sec_structured",
            basis_date=end,
            taxonomy_concept=f"{item['taxonomy']}:{concept}",
            confidence="medium",
            metadata={
                **meta,
                "basis_evidence": "Current accession DEI cover instant or current period-end with no intervening split",
            },
        )
        made += added
        skipped += not added
    return {"created": made, "skipped": skipped, "unavailable": rejected}
