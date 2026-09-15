import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.config import Settings
from valuation_engine.db.schema import Filing, SourceDocument
from valuation_engine.db.store import add_fact, company, document, issue
from valuation_engine.ingestion.http import SourceClient
from valuation_engine.normalization.mapping import CONCEPTS, VERSION
from valuation_engine.time import ET, aware


def filing_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(zip(payload, values, strict=True)) for values in zip(*payload.values(), strict=True)
    ]


def parse_acceptance(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # SEC header timestamps without offset are Eastern; API strings normally carry Z.
    return aware(parsed.replace(tzinfo=ET) if parsed.tzinfo is None else parsed)


def ingest_sec(
    db: Session,
    settings: Settings,
    client: SourceClient | None = None,
    *,
    download_filings: bool = True,
) -> dict[str, Any]:
    http = client or SourceClient(settings.require_sec_identity())
    co = company(db)
    audit = dict(
        filings_created=0,
        filings_skipped=0,
        facts_created=0,
        facts_skipped=0,
        documents_created=0,
        documents_skipped=0,
    )

    def archive(content: bytes, **kwargs: Any) -> SourceDocument:
        exists = db.scalar(
            select(SourceDocument.id).where(
                SourceDocument.source_url == kwargs["url"],
                SourceDocument.content_hash == hashlib.sha256(content).hexdigest(),
            )
        )
        row = document(db, settings.qve_raw_dir, content, **kwargs)
        audit["documents_skipped" if exists is not None else "documents_created"] += 1
        return row

    base = "https://data.sec.gov"
    sub_url = f"{base}/submissions/CIK{co.cik}.json"
    raw = http.get(sub_url)
    submissions = json.loads(raw)
    archive(
        raw,
        url=sub_url,
        company_id=co.id,
        provider="SEC",
        kind="submissions",
        published_at=None,
    )
    rows = filing_rows(submissions["filings"]["recent"])
    for chunk in submissions["filings"].get("files", []):
        if chunk.get("filingTo", "") < "2019-01-01":
            continue
        url = f"{base}/submissions/{chunk['name']}"
        history = http.get(url)
        archive(
            history,
            url=url,
            company_id=co.id,
            provider="SEC",
            kind="submissions",
            published_at=None,
        )
        rows.extend(filing_rows(json.loads(history)))
    filings: dict[str, Filing] = {}
    for row in rows:
        if (
            row["form"] not in ("10-Q", "10-K", "10-Q/A", "10-K/A", "8-K", "8-K/A")
            or row["filingDate"] < "2019-01-01"
        ):
            continue
        acc = row["accessionNumber"]
        if acc in filings:
            continue
        filing = db.scalar(select(Filing).where(Filing.accession_number == acc))
        if filing is None:
            audit["filings_created"] += 1
            filing = Filing(
                company_id=co.id,
                accession_number=acc,
                form_type=row["form"],
                period_end=datetime.fromisoformat(row["reportDate"]).date()
                if row.get("reportDate")
                else None,
                filing_date=datetime.fromisoformat(row["filingDate"]).date(),
                accepted_timestamp=parse_acceptance(row.get("acceptanceDateTime")),
                source_url=f"https://www.sec.gov/Archives/edgar/data/{int(co.cik)}/{acc.replace('-', '')}/{row['primaryDocument']}",
                is_amendment=row["form"].endswith("/A"),
            )
            db.add(filing)
            db.flush()
        else:
            audit["filings_skipped"] += 1
        filings[acc] = filing
    url = f"{base}/api/xbrl/companyfacts/CIK{co.cik}.json"
    content = http.get(url)
    payload = json.loads(content)
    api_doc = archive(
        content,
        url=url,
        company_id=co.id,
        provider="SEC",
        kind="companyfacts",
        published_at=None,
    )
    counts = {"created": 0, "skipped": 0, "filings": len(filings)}
    docs: dict[int, SourceDocument] = {}
    grouped: dict[int, list[dict[str, Any]]] = {}
    excluded_units: list[dict[str, str]] = []
    for taxonomy, concepts in payload["facts"].items():
        for metric, aliases in CONCEPTS.items():
            for rank, concept in enumerate(aliases):
                for unit, observations in concepts.get(concept, {}).get("units", {}).items():
                    expected = (
                        "shares"
                        if "shares" in metric
                        else "USD/shares"
                        if metric == "eps_diluted"
                        else "USD"
                    )
                    if unit != expected:
                        excluded_units.append(
                            {
                                "metric": metric,
                                "concept": f"{taxonomy}:{concept}",
                                "unit": unit,
                                "expected": expected,
                            }
                        )
                        continue
                    for obs in observations:
                        filing = filings.get(obs.get("accn"))
                        if filing is None or obs["end"] < "2019-01-01":
                            continue
                        grouped.setdefault(filing.id, []).append(
                            {
                                "metric": metric,
                                "taxonomy": taxonomy,
                                "concept": concept,
                                "rank": rank,
                                "unit": unit,
                                "obs": obs,
                            }
                        )
    by_id = {x.id: x for x in filings.values()}
    share_results = []
    for filing_id, values in grouped.items():
        filing = by_id[filing_id]
        reported = filing.accepted_timestamp or datetime.combine(
            filing.filing_date + timedelta(days=1), datetime.min.time(), ET
        )
        # SEC acceptance is a proxy, not exact dissemination; add documented safety buffer.
        available = reported + timedelta(minutes=3) if filing.accepted_timestamp else reported
        doc = archive(
            json.dumps(values, sort_keys=True).encode(),
            url=filing.source_url + "#companyfacts-extract",
            company_id=co.id,
            provider="SEC",
            kind="XBRL accession extract",
            published_at=filing.accepted_timestamp,
            filing_id=filing.id,
            metadata={
                "api_source_document_id": api_doc.id,
                "availability_policy": "accepted_plus_3m"
                if filing.accepted_timestamp
                else "date_only_next_midnight",
                "original_document_url": filing.source_url,
            },
        )
        docs[filing_id] = doc
        from valuation_engine.hardening.shares import ingest_structured_shares

        share_results.append(
            {
                "accession": filing.accession_number,
                **ingest_structured_shares(db, filing, doc, values),
            }
        )
        if doc.metadata_json.get("changed_content"):
            available = max(available, doc.retrieved_at)
            issue(
                db,
                "revised_api_extract",
                {"policy": "Changed accession extract only available at retrieval"},
                company_id=co.id,
                document_id=doc.id,
            )
        for item in values:
            obs = item["obs"]
            end = datetime.fromisoformat(obs["end"]).date()
            start = datetime.fromisoformat(obs["start"]).date() if obs.get("start") else None
            # Fiscal period derived from economic end date, never SEC fy/fp (filing context).
            fy = end.year if end.month == 1 else end.year + 1
            fq = (
                4
                if end.month == 1
                else 1
                if end.month in (4, 5)
                else 2
                if end.month in (7, 8)
                else 3
                if end.month in (10, 11)
                else None
            )
            if fq is None:
                issue(
                    db,
                    "unmapped_period",
                    {"end": str(end)},
                    company_id=co.id,
                    document_id=doc.id,
                    metric=item["metric"],
                )
                continue
            from valuation_engine.ingestion.ir import fiscal_start

            expected_end = (
                fiscal_start(fy, fq + 1) - timedelta(days=1)
                if fq < 4
                else fiscal_start(fy + 1, 1) - timedelta(days=1)
            )
            if end != expected_end:
                issue(
                    db,
                    "non_fiscal_period_end",
                    {"end": str(end), "expected_end": str(expected_end)},
                    company_id=co.id,
                    document_id=doc.id,
                    metric=item["metric"],
                )
                continue
            if end == filing.period_end:
                filing.fiscal_year, filing.fiscal_quarter = fy, fq
            days = (end - start).days + 1 if start else 0
            kind = (
                "instant"
                if not start
                else "quarter"
                if 75 <= days <= 105
                else "annual"
                if 350 <= days <= 380
                else "ytd"
                if 150 <= days <= 300
                else None
            )
            if kind is None:
                issue(
                    db,
                    "unsupported_duration",
                    {"days": days},
                    company_id=co.id,
                    document_id=doc.id,
                    metric=item["metric"],
                )
                continue
            _, added = add_fact(
                db,
                company_id=co.id,
                filing_id=filing.id,
                metric_name=item["metric"],
                taxonomy_name=f"{item['taxonomy']}:{item['concept']}",
                value=Decimal(str(obs["val"])),
                unit=item["unit"],
                period_start=start,
                period_end=end,
                fiscal_year=fy,
                fiscal_quarter=fq,
                duration_kind=kind,
                frame=obs.get("frame"),
                reported_at=reported,
                available_at=available,
                source_document_id=doc.id,
                source_priority=10 + item["rank"],
                formula_version=VERSION,
                metadata_json={
                    "sec_fy": obs.get("fy"),
                    "sec_fp": obs.get("fp"),
                    "accession": obs["accn"],
                    "share_basis": "as_presented_in_accession",
                    "acceptance_is_proxy": True,
                    "timestamp_precision": "inferred_acceptance_buffer"
                    if filing.accepted_timestamp
                    else "date_only",
                    "timestamp_source": filing.source_url,
                    "timestamp_confidence": "medium" if filing.accepted_timestamp else "low",
                    "fallback_reason": "SEC acceptance plus 3 minute dissemination proxy; not verified public availability"
                    if filing.accepted_timestamp
                    else "Acceptance unavailable; next midnight ET after filing date",
                    "accepted_timestamp": filing.accepted_timestamp.isoformat()
                    if filing.accepted_timestamp
                    else None,
                    "accepted_timestamp_precision": "exact"
                    if filing.accepted_timestamp
                    else "unresolved",
                    "filing_date": str(filing.filing_date),
                    "timezone": "America/New_York",
                },
            )
            counts["created" if added else "skipped"] += 1
    errors = []
    primary_created = 0
    if download_filings:
        for filing in filings.values():
            if not filing.form_type.startswith(("10-Q", "10-K")):
                continue
            if db.scalar(
                select(SourceDocument.id).where(
                    SourceDocument.filing_id == filing.id,
                    SourceDocument.document_type == "SEC primary filing",
                )
            ):
                audit["documents_skipped"] += 1
                continue
            try:
                body = http.get(filing.source_url)
                if b"<html" not in body.lower():
                    raise ValueError("SEC primary document is not HTML/iXBRL")
                archive(
                    body,
                    url=filing.source_url,
                    company_id=co.id,
                    provider="SEC",
                    kind="SEC primary filing",
                    published_at=None,
                    filing_id=filing.id,
                    metadata={
                        "accession": filing.accession_number,
                        "accepted_timestamp": filing.accepted_timestamp.isoformat()
                        if filing.accepted_timestamp
                        else None,
                        "filing_date": str(filing.filing_date),
                        "timestamp_precision": "exact_acceptance_not_publication"
                        if filing.accepted_timestamp
                        else "date_only",
                    },
                )
                primary_created += 1
            except Exception as exc:
                errors.append({"accession": filing.accession_number, "error": str(exc)})
    from valuation_engine.hardening.shares import ingest_cover_shares

    cover = ingest_cover_shares(db, co.id)
    audit.update(facts_created=counts["created"], facts_skipped=counts["skipped"])
    return {
        **counts,
        **audit,
        "primary_documents_created": primary_created,
        "errors": errors,
        "cover_shares": cover,
        "structured_shares": share_results,
        "excluded_units": excluded_units,
    }
