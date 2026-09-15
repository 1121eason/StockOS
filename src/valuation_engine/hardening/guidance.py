from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.db.schema import GuidanceItem, SourceDocument
from valuation_engine.db.store import digest, read_document
from valuation_engine.ingestion.ir import parse_release

METRICS = ("revenue", "gross_margin", "operating_expenses", "tax_rate")


def guidance_coverage(db: Session, company_id: int) -> list[dict[str, Any]]:
    result = []
    for doc in db.scalars(
        select(SourceDocument)
        .where(
            SourceDocument.company_id == company_id, SourceDocument.source_provider == "NVIDIA IR"
        )
        .order_by(SourceDocument.id)
    ):
        fy, fq = doc.metadata_json["fiscal_year"], doc.metadata_json["fiscal_quarter"]
        parsed = parse_release(read_document(doc), fy, fq)
        candidates = parsed["guidance"]
        for metric in METRICS:
            matches = [g for g in candidates if g["metric"] == metric]
            ids = [
                db.scalar(
                    select(GuidanceItem.id).where(GuidanceItem.identity_key == digest([doc.id, g]))
                )
                for g in matches
            ]
            status = (
                "structured"
                if len(matches) == 1 and all(ids)
                else "ambiguous"
                if len(matches) > 1
                else "text-only"
                if metric.replace("_", " ") in parsed["outlook"].lower()
                else "unavailable"
            )
            result.append(
                {
                    "quarter": f"FY{fy}-Q{fq}",
                    "metric": metric,
                    "status": status,
                    "guidance_item_ids": ids,
                    "source_document_id": doc.id,
                    "source_url": doc.source_url,
                    "values": [
                        {k: str(v) if v is not None else None for k, v in g.items()}
                        for g in matches
                    ],
                    "parser_version": "deterministic-guidance-1.1",
                    "raw_outlook": parsed["outlook"] if status != "structured" else None,
                }
            )
    return result


def current_guidance_ids(db: Session, company_id: int) -> set[int]:
    return {i for row in guidance_coverage(db, company_id) for i in row["guidance_item_ids"] if i}
