"""Bounded NVIDIA official-source collection; parsed facts remain staging data."""

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from valuation_engine.ingestion.ir import parse_release
from valuation_engine.research.numbers import canonical

HOST = "nvidianews.nvidia.com"
INDEXES = (
    f"https://{HOST}/news",
    f"https://{HOST}/helper-search-news?ct=releases&page=1&q=financial+results",
)
PARSER = "ExistingNVIDIAReleaseParser_ProductStagingV1"


def official_url(value: str, *, index: bool = False) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or url.hostname != HOST
        or url.username
        or url.password
        or url.port not in (None, 443)
        or (not index and not re.fullmatch(r"/news/[a-z0-9-]+/?", url.path))
    ):
        raise ValueError("unapproved_source_url")
    return f"https://{HOST}{url.path.rstrip('/')}" + (
        "?" + url.query if index and url.query else ""
    )


def download(url: str, *, index: bool = False) -> bytes:
    """Validate every redirect and bound bytes while streaming, not after download."""
    url = official_url(url, index=index)
    with httpx.Client(timeout=15, follow_redirects=False) as client:
        for _ in range(4):
            with client.stream("GET", url, headers={"User-Agent": "StockOS research/1.0"}) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    url = official_url(urljoin(url, r.headers["location"]), index=index)
                    continue
                r.raise_for_status()
                if "html" not in r.headers.get("content-type", "").lower():
                    raise ValueError("unexpected_source_content_type")
                parts, size = [], 0
                for part in r.iter_bytes():
                    size += len(part)
                    if size > 4_000_000:
                        raise ValueError("source_too_large")
                    parts.append(part)
                return b"".join(parts)
    raise ValueError("source_redirect_limit")


def discover(content: bytes) -> list[str]:
    links = []
    for node in BeautifulSoup(content, "html.parser").select("a[href]"):
        try:
            url = official_url(urljoin(f"https://{HOST}/", str(node["href"])))
        except ValueError:
            continue
        if url not in links:
            links.append(url)
    if not links:
        raise ValueError("official_index_has_no_article_links")
    return links[:100]


def describe(content: bytes, url: str, received_at: datetime) -> dict:
    soup = BeautifulSoup(content, "html.parser")
    heading = soup.select_one("h1")
    if heading is None or not heading.get_text(strip=True):
        raise ValueError("official_article_title_missing")
    title = heading.get_text(" ", strip=True)
    body = soup.select_one(".article-body")
    if body is None:
        raise ValueError("official_article_body_missing")
    for node in body.select("script,style,noscript"):
        node.decompose()
    text = re.sub(r"\s+", " ", body.get_text(" ", strip=True))
    date_node = soup.select_one(".article-date, time, .date")
    day = None
    if date_node:
        match = re.search(r"[A-Za-z]+ \d{1,2}, \d{4}", date_node.get_text(" ", strip=True))
        if match:
            for fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    day = datetime.strptime(match[0], fmt).date().isoformat()
                    break
                except ValueError:
                    pass
    if day and day > received_at.astimezone(UTC).date().isoformat():
        raise ValueError("future_publication_date")
    result = {
        "title": title,
        "event_fingerprint": hashlib.sha256((title + "\n" + text).encode()).hexdigest(),
        "url": official_url(url),
        "source_hash": hashlib.sha256(content).hexdigest(),
        "received_at": received_at.isoformat(),
        "publication_date": day,
        "published_at": None,
        "available_at": received_at.isoformat(),
        "availability_policy": "observed_now_not_backdated_to_publication_day",
        "kind": "company_announcement",
        "status": "awaiting_research",
        "model_impact": "未完成證據與影響審查，尚未調整估值",
        "parser_version": PARSER,
        "financials": None,
    }
    match = re.search(
        r"financial results for (first|second|third|fourth) quarter (?:and )?fiscal (\d{4})",
        title,
        re.I,
    )
    if match:
        fy = int(match[2])
        fq = ("first", "second", "third", "fourth").index(match[1].lower()) + 1
        result.update(kind="earnings_release", quarter=f"FY{fy}-Q{fq}")
        try:
            parsed = parse_release(content, fy, fq)
            result.update(
                status="parsed_pending_reconciliation",
                financials=canonical(parsed),
                model_impact="財務與指引已解析；待對帳及新一版研究計算",
            )
        except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
            result.update(status="parse_blocked", parse_error=type(exc).__name__)
    return result
