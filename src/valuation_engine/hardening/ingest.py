import hashlib
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag
from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.config import Settings
from valuation_engine.db.schema import CorporateAction, SourceDocument
from valuation_engine.db.store import company, digest, document, read_document
from valuation_engine.hardening.availability import add_evidence
from valuation_engine.ingestion.ir import parse_release
from valuation_engine.time import ET, aware


def import_timestamp_evidence(
    db: Session, settings: Settings, manifest: Path
) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    for item in json.loads(manifest.read_text()):
        if not item.get("source_document_id") or not item.get("path"):
            continue
        source = db.get(SourceDocument, item["source_document_id"])
        assert source is not None
        raw = Path(item["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != Path(item["path"]).name:
            raise ValueError("Evidence hash mismatch")
        soup = BeautifulSoup(raw, "html.parser")
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        if "404 Page Not Found" in text:
            continue
        fy, fq = source.metadata_json["fiscal_year"], source.metadata_json["fiscal_quarter"]
        original = parse_release(read_document(source, settings.qve_raw_dir), fy, fq)
        # GlobeNewswire shortens HTML title; use the full H1 as the parser title.
        if soup.h1 and soup.title:
            soup.title.string = soup.h1.get_text()
        try:
            distributed = parse_release(str(soup).encode(), fy, fq)
        except ValueError as exc:
            report.append({"quarter": f"FY{fy}-Q{fq}", "status": "unverified", "reason": str(exc)})
            continue
        left = {(f["metric"], f["kind"]): f["value"] for f in original["facts"]}
        right = {(f["metric"], f["kind"]): f["value"] for f in distributed["facts"]}
        # All locally parsed facts must be in the contemporaneous distributed release.
        unmatched = [str(k) for k, v in left.items() if right.get(k) != v]
        if unmatched:
            report.append(
                {"quarter": f"FY{fy}-Q{fq}", "status": "content_mismatch", "metrics": unmatched}
            )
            continue
        time_node = soup.find("time", datetime=True)
        if isinstance(time_node, Tag) and "globenewswire.com" in item["url"]:
            published = (
                aware(datetime.fromisoformat(str(time_node["datetime"]).replace("Z", "+00:00")))
                .astimezone(ET)
                .replace(second=0, microsecond=0)
            )
        else:
            match = re.search(
                r"Published ([A-Za-z]+ \d{1,2}, \d{4}) (\d{1,2}:\d\d[ap]m) (EST|EDT)", text
            )
            if not match:
                continue
            published = datetime.strptime(match[1] + " " + match[2], "%b %d, %Y %I:%M%p").replace(
                tzinfo=ET
            )
            if published.tzname() != match[3]:
                raise ValueError("Publication timezone disagrees with DST calendar")
        if str(published.date()) != original["publication_date"]:
            raise ValueError("Distribution timestamp date does not match release date")
        evidence = document(
            db,
            settings.qve_raw_dir,
            raw,
            url=item["url"],
            company_id=source.company_id,
            provider="NVIDIA issuer distribution",
            kind="Publication timestamp evidence",
            published_at=published,
            metadata={
                "fiscal_year": fy,
                "fiscal_quarter": fq,
                "matched_financial_metrics": len(left),
                "timestamp_precision": "minute",
                "timestamp_field": "visible publication time",
                "retrieved_by": "M1.1 official distribution fetch",
            },
        )
        # Guidance must also match normalized deterministic parser output before sharing a time.
        scopes: tuple[str, ...] = ("financial_fact",)
        if digest(original["segments"]) == digest(distributed["segments"]):
            scopes += ("segment",)

        def semantic(gs: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return sorted(
                ({k: v for k, v in g.items() if k != "raw_text"} for g in gs),
                key=lambda g: g["metric"],
            )

        if digest(semantic(original["guidance"])) == digest(semantic(distributed["guidance"])):
            scopes += ("guidance",)
        add_evidence(db, source, evidence, published, "minute", original["available"], scopes)
        report.append(
            {
                "quarter": f"FY{fy}-Q{fq}",
                "source_document_id": source.id,
                "evidence_document_id": evidence.id,
                "published_at": published.isoformat(),
                "information_available_at": (published + timedelta(minutes=1)).isoformat(),
                "precision": "minute",
                "matched_metrics": len(left),
                "scopes": scopes,
                "status": "verified",
            }
        )
    return report


def add_date_fallbacks(db: Session) -> None:
    for source in db.scalars(
        select(SourceDocument).where(SourceDocument.source_provider == "NVIDIA IR")
    ):
        day = date.fromisoformat(source.metadata_json["publication_date"])
        fallback = datetime.combine(day + timedelta(days=1), datetime.min.time(), ET)
        add_evidence(db, source, source, None, "date_only", fallback)


def ingest_splits(db: Session, settings: Settings, manifest: Path) -> dict[str, int]:
    co = company(db)
    counts = {"created": 0, "skipped": 0}
    for item in json.loads(manifest.read_text()):
        raw = Path(item["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != Path(item["path"]).name:
            raise ValueError("Evidence hash mismatch")
        doc = document(
            db,
            settings.qve_raw_dir,
            raw,
            url=item["url"],
            company_id=co.id,
            provider="NVIDIA",
            kind="Official stock split evidence",
            published_at=None,
            metadata={
                "verification": item["verification"],
                "scope": "target historical period FY2021-Q1 onward",
            },
        )
        key = digest(
            [co.id, item["split_date"], item["numerator"], item["denominator"], doc.id, "split-1.1"]
        )
        if db.scalar(select(CorporateAction.id).where(CorporateAction.identity_key == key)):
            counts["skipped"] += 1
            continue
        db.add(
            CorporateAction(
                identity_key=key,
                company_id=co.id,
                action_type="split",
                split_date=date.fromisoformat(item["split_date"]),
                effective_date=date.fromisoformat(item["effective_date"]),
                ratio_numerator=Decimal(item["numerator"]),
                ratio_denominator=Decimal(item["denominator"]),
                adjustment_factor=Decimal(item["numerator"]) / Decimal(item["denominator"]),
                announced_at=datetime.fromisoformat(item["announced_at"]),
                source_document_id=doc.id,
                metadata_json={
                    "verification": item["verification"],
                    "announcement_precision": "date_only_next_midnight",
                    "factor_definition": "new shares per old share; divide EPS and prices, multiply shares",
                },
            )
        )
        counts["created"] += 1
    db.flush()
    return counts
