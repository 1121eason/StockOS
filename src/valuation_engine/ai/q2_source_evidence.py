"""Verify fresh official page observations against the unchanged Q2 package.

DOM serialization is not the original HTTP byte stream. Exact narrative text
and conservative availability bounds are verified separately from historical
minute assertions and original-byte attestation.
"""

import re
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from valuation_engine.ai.native_preflight import PACKAGE_HASH, inspect_preparation, load_bound, sha
from valuation_engine.ai.sources import blocks

ET = ZoneInfo("America/New_York")


def filing_bound(index_text, source_url):
    accession = re.search(r"/([0-9]{18})/([^/]+)$", source_url)
    if not accession:
        raise ValueError("SEC identity missing")
    number, primary = accession.groups()
    dashed = f"{number[:10]}-{number[10:12]}-{number[12:]}"
    if dashed not in index_text or primary not in index_text or "0001045810" not in index_text:
        raise ValueError("SEC index identity mismatch")
    accepted = re.search(r"\bAccepted\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", index_text)
    filed = re.search(r"\bFiling Date\s+(\d{4}-\d{2}-\d{2})", index_text)
    if not accepted or not filed:
        raise ValueError("Explicit SEC acceptance and filing dates required")
    accepted_time = datetime.fromisoformat(accepted[1]).replace(tzinfo=ET)
    date = datetime.fromisoformat(filed[1]).date()
    upper = max(
        accepted_time + timedelta(minutes=3), datetime.combine(date + timedelta(days=1), time(), ET)
    )
    return {
        "accepted_at": accepted_time.astimezone(UTC).isoformat(),
        "filing_date": date.isoformat(),
        "available_upper_bound": upper.astimezone(UTC).isoformat(),
        "precision": "CONSERVATIVE_NEXT_FILING_DAY_BOUND_NOT_EXACT_DISSEMINATION",
    }


def release_bound(content, expected_published_at):
    date = datetime.fromisoformat(expected_published_at).astimezone(ET).date()
    expected = f"{date.strftime('%B')} {date.day}, {date.year}"
    text = " ".join(BeautifulSoup(content, "html.parser").get_text(" ", strip=True).split())
    if expected not in text:
        raise ValueError("Official release publication day missing")
    return {
        "publication_day": date.isoformat(),
        "available_upper_bound": datetime.combine(date + timedelta(days=1), time(), ET)
        .astimezone(UTC)
        .isoformat(),
        "precision": "OFFICIAL_VISIBLE_DAY_END_BOUND_MINUTE_ASSERTION_UNVERIFIED",
    }


def verify_text(doc, content, selected):
    derived, _ = blocks(
        SimpleNamespace(
            id=doc["source_document_id"],
            content_hash=doc["source_hash"],
            document_type=doc["document_type"],
        ),
        content,
    )
    current = {b["text"] for b in derived}
    missing = [b["block_id"] for b in selected if b["text"] not in current]
    if not selected or missing:
        raise ValueError("Current official narrative is incomplete or differs")
    return {
        "selected_blocks": len(selected),
        "exact_narrative_matches": len(selected),
        "current_parsed_blocks": len(derived),
        "comparison": "UNCHANGED_CANONICAL_PARSER_TEXT_NO_WORD_OR_PUNCTUATION_NORMALIZATION",
    }


def verify(preparation: Path, raw: Path, browser_evidence: Path, release_captures: Path):
    plan, documents = inspect_preparation(preparation, raw)
    package = load_bound(preparation / "package.json", "package_hash", PACKAGE_HASH)
    cutoff = datetime.fromisoformat(plan["information_cutoff"])
    results = []
    for doc in documents:
        sid = doc["source_document_id"]
        selected = [
            b for b in package["prepared"]["sources"]["blocks"] if b["source_document_id"] == sid
        ]
        if doc["document_type"] == "Earnings Release":
            path = release_captures / f"source-{sid}.html"
            content = path.read_bytes()
            timing = release_bound(content, doc["published_at"])
            observation = "OFFICIAL_HTTPS_CAPTURE"
            extra = {}
        else:
            path = browser_evidence / f"sec-{sid}-dom-full.html"
            content = path.read_bytes()
            if b"[Truncated]" in content[-100:]:
                raise ValueError("Browser DOM capture was truncated")
            index = browser_evidence / f"sec-{sid}-index-text.txt"
            timing = filing_bound(index.read_text(), doc["source_url"])
            observation = "BROWSER_RENDERED_OFFICIAL_DOM_NOT_HTTP_ORIGINAL_BYTES"
            extra = {
                "index_sha256": sha(index.read_bytes()),
                "index_url": doc["source_url"].rsplit("/", 1)[0]
                + "/"
                + doc["source_url"].split("/")[-2][:10]
                + "-"
                + doc["source_url"].split("/")[-2][10:12]
                + "-"
                + doc["source_url"].split("/")[-2][12:]
                + "-index.htm",
            }
        bound = datetime.fromisoformat(timing["available_upper_bound"])
        if not cutoff - timedelta(days=200) <= bound <= cutoff:
            raise ValueError("Independently observed conservative bound outside PIT window")
        results.append(
            {
                "source_document_id": sid,
                "source_url": doc["source_url"],
                "cached_sha256": doc["source_hash"],
                "observed_capture_sha256": sha(content),
                "observation": observation,
                "text": verify_text(doc, content, selected),
                "timing": timing,
                **extra,
            }
        )
    return {
        "version": "NVDAQ2CurrentTextAndPITBoundEvidenceV1",
        "package_hash": PACKAGE_HASH,
        "information_cutoff": cutoff.isoformat(),
        "documents": results,
        "exact_text_matches": sum(d["text"]["exact_narrative_matches"] for d in results),
        "status": "VERIFIED_CURRENT_NARRATIVE_AND_CONSERVATIVE_PIT_BOUND",
        "historical_minute_assertions": "UNVERIFIED",
        "original_http_byte_attestation": "NOT_ESTABLISHED",
        "classification": "RECONSTRUCTED_ADVISORY_INPUTS_NOT_HISTORICAL_OOS",
        "formal_db_writes": 0,
    }
