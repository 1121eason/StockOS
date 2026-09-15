"""Official-source PIT retrieval, narrative-only blocks and explicit coverage gaps."""

import hashlib
import re
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from sqlalchemy import select

from valuation_engine.db.schema import AvailabilityEvidence, Filing, SourceDocument
from valuation_engine.db.store import read_document
from valuation_engine.time import ET

KINDS = {
    "Earnings Release",
    "SEC primary filing",
    "Official Earnings Call Transcript",
    "Official management Q&A",
    "NVIDIA Investor Presentation",
    "SEC exhibit",
}
DOMAINS = {
    "nvidianews.nvidia.com",
    "investor.nvidia.com",
    "s201.q4cdn.com",
    "www.sec.gov",
    "sec.gov",
}
INJECTION = re.compile(
    r"ignore (?:all |any |the )?(?:previous|prior|system) instructions|system\s*prompt|developer message|reveal.{0,20}(?:secret|key)|<\|(?:system|im_start)|you are (?:chatgpt|an ai)|execute.{0,15}(?:command|code)",
    re.I,
)
PRICE = re.compile(
    r"stock price|share price|trading price|market price|closing price|aggregate market value|market capitalization|market cap\b|total shareholder return|stock performance|price target|target price|buy.{0,8}sell recommendation|NASDAQ\s*:\s*NVDA",
    re.I,
)


def blocks(source, content):
    if content.startswith(b"%PDF"):
        from valuation_engine.ai.pdf_text import paragraphs

        parsed = paragraphs(
            content,
            transcript="Transcript" in source.document_type or "Q&A" in source.document_type,
        )
        result, removed = [], []
        for paragraph in parsed:
            value = paragraph["text"]
            reason = (
                "prompt_injection_quarantine"
                if INJECTION.search(value)
                else "price_context_removed"
                if PRICE.search(value)
                else None
            )
            sha = hashlib.sha256(value.encode()).hexdigest()
            if reason:
                removed.append({"reason": reason, "block_hash": sha})
            else:
                result.append(
                    {
                        "block_id": f"{source.id}:" + sha[:20],
                        "source_document_id": source.id,
                        "source_hash": source.content_hash,
                        **paragraph,
                    }
                )
        return result, removed
    soup = BeautifulSoup(content, "html.parser")
    root = (
        soup.select_one(".article-body")
        if source.document_type == "Earnings Release"
        else soup.body
    )
    if root is None:
        return [], [{"reason": "no_verified_narrative_container"}]
    for el in list(
        root.find_all(["script", "style", "noscript", "table", "header", "footer", "nav"])
    ):
        el.decompose()
    for el in list(root.find_all()):
        if el.name is None or el.attrs is None:
            continue
        style = str(el.get("style", "")).replace(" ", "").lower()
        if (
            el.name.lower() in ("ix:header", "ix:hidden", "xbrli:context", "xbrli:unit")
            or "display:none" in style
            or el.has_attr("hidden")
        ):
            el.decompose()
    candidates = root.find_all(["p", "li", "div", "h1", "h2", "h3", "h4"])
    result, removed = [], []
    section = "narrative"
    seen = set()
    for el in candidates:
        if el.find(["p", "li", "div", "h1", "h2", "h3", "h4"]):
            continue
        value = " ".join(el.get_text(" ", strip=True).split())
        if not value or value in seen:
            continue
        seen.add(value)
        if len(value) < 100 and (
            el.name.startswith("h")
            or re.match(r"^(?:Item|Risk Factors|Management|Outlook|Business)", value, re.I)
        ):
            section = value
        if len(value) < 35 or len(value.split()) < 7:
            continue
        reason = (
            "prompt_injection_quarantine"
            if INJECTION.search(value)
            else "price_context_removed"
            if PRICE.search(value)
            else None
        )
        if reason:
            removed.append(
                {"reason": reason, "block_hash": hashlib.sha256(value.encode()).hexdigest()}
            )
            continue
        # Preserve whole paragraph; do not cut off negations or qualifying text.
        key = f"{source.id}:" + hashlib.sha256(value.encode()).hexdigest()[:20]
        result.append(
            {
                "block_id": key,
                "source_document_id": source.id,
                "source_hash": source.content_hash,
                "section": section,
                "text": value,
            }
        )
    return result, removed


def retrieve(db, company_id, cutoff, raw_dir=None):
    evidence = list(
        db.scalars(
            select(AvailabilityEvidence).where(
                AvailabilityEvidence.information_available_at <= cutoff,
                AvailabilityEvidence.scope.in_(("financial_fact", "ai_narrative")),
            )
        )
    )
    byid: dict[int, AvailabilityEvidence] = {}
    rank = {"exact": 0, "minute": 1, "date_only": 2, "inferred_after_close": 3}
    for e in sorted(evidence, key=lambda x: (rank[x.timestamp_precision], -x.id)):
        byid.setdefault(e.source_document_id, e)
    candidates = []
    for source in db.scalars(select(SourceDocument).where(SourceDocument.company_id == company_id)):
        if source.document_type not in KINDS or urlparse(source.source_url).hostname not in DOMAINS:
            continue
        e = byid.get(source.id)
        if e is None and source.document_type == "SEC primary filing" and source.filing_id:
            filing = db.get(Filing, source.filing_id)
            if filing and filing.company_id == company_id and filing.accepted_timestamp:
                # SEC acceptance is not proven publication. Use the existing conservative
                # filing-date next-midnight bound, never silently call acceptance exact publication.
                bound = max(
                    filing.accepted_timestamp + timedelta(minutes=1),
                    datetime.combine(filing.filing_date + timedelta(days=1), time(), ET),
                )
                if bound <= cutoff:
                    e = SimpleNamespace(
                        id=None,
                        published_at=None,
                        information_available_at=bound,
                        timestamp_precision="date_only_SEC_filing_bound",
                    )
        # A changed web page cannot inherit the old historical publication date.
        if e is None or (
            source.metadata_json.get("changed_content") and source.retrieved_at > cutoff
        ):
            continue
        if e.information_available_at < cutoff - timedelta(days=200):
            continue
        candidates.append((source, e))
    candidates.sort(key=lambda x: (x[1].information_available_at, x[0].id), reverse=True)
    # Explicit window: two most recent releases, two filings, one official call/Q&A/presentation.
    selected = []
    for kinds, limit in [
        ({"Earnings Release"}, 2),
        ({"SEC primary filing", "SEC exhibit"}, 2),
        (
            {
                "Official Earnings Call Transcript",
                "Official management Q&A",
                "NVIDIA Investor Presentation",
            },
            1,
        ),
    ]:
        selected.extend([x for x in candidates if x[0].document_type in kinds][:limit])
    documents, all_blocks, omissions = [], [], []
    for source, e in selected:
        content = read_document(source, raw_dir)
        rows, excluded = blocks(source, content)
        meta = {
            "source_document_id": source.id,
            "source_url": source.source_url,
            "source_hash": source.content_hash,
            "document_type": source.document_type,
            "published_at": e.published_at.isoformat() if e.published_at else None,
            "available_at": e.information_available_at.isoformat(),
            "timestamp_precision": e.timestamp_precision,
            "availability_evidence_id": e.id,
            "block_count": len(rows),
            "tier": 2
            if "Transcript" in source.document_type or "Q&A" in source.document_type
            else 1,
        }
        documents.append(meta)
        all_blocks.extend(
            [
                {
                    **r,
                    "published_at": meta["published_at"],
                    "available_at": meta["available_at"],
                    "tier": meta["tier"],
                }
                for r in rows
            ]
        )
        omissions.extend([{"source_document_id": source.id, **x} for x in excluded])
    return {
        "documents": documents,
        "blocks": all_blocks,
        "excluded_blocks": omissions,
        "coverage": {
            "lookback_days": 200,
            "current_and_prior_release_limit": 2,
            "filing_limit": 2,
            "official_call_status": "available"
            if any(
                "Transcript" in d["document_type"] or "Q&A" in d["document_type"] for d in documents
            )
            else "missing",
            "filing_status": "available"
            if any(d["document_type"] == "SEC primary filing" for d in documents)
            else "missing",
            "narrative_blocks": len(all_blocks),
            "tables_excluded": True,
        },
    }


def chunks(rows, limit=18000):
    batch: list[dict] = []
    size = 0
    for row in rows:
        if batch and size + len(row["text"]) > limit:
            yield batch
            batch, size = [], 0
        batch.append(row)
        size += len(row["text"])
    if batch:
        yield batch
