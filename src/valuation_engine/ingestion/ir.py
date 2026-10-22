import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from bs4 import BeautifulSoup, Tag
from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.calendar_math import fiscal_start as fiscal_start
from valuation_engine.config import Settings
from valuation_engine.db.schema import GuidanceItem, SegmentFact
from valuation_engine.db.store import add_fact, company, digest, document, issue
from valuation_engine.ingestion.http import SourceClient
from valuation_engine.normalization.mapping import INSTANT, VERSION
from valuation_engine.time import ET

LABELS = {
    "cash, cash equivalents and marketable securities": "cash_and_marketable_securities",
    "purchase related to property and equipment and intangible assets": "capex",
    "stock based compensation expense": "sbc",
    "revenue": "revenue",
    "cost of revenue": "cost_of_revenue",
    "gross profit": "gross_profit",
    "gross margin": "gross_margin_reported",
    "operating expenses": "operating_expenses",
    "total operating expenses": "operating_expenses",
    "research and development": "research_and_development",
    "sales, general and administrative": "sga",
    "selling, general and administrative": "sga",
    "operating income": "operating_income",
    "net income": "net_income",
    "diluted earnings per share": "eps_diluted",
    "cash and cash equivalents": "cash",
    "marketable securities": "marketable_securities",
    "marketable debt securities": "marketable_debt_securities",
    "marketable equity securities": "marketable_equity_securities",
    "accounts receivable, net": "accounts_receivable",
    "inventories": "inventory",
    "total assets": "total_assets",
    "accounts payable": "accounts_payable",
    "short-term debt": "debt_current",
    "long-term debt": "debt_noncurrent",
    "total shareholders' equity": "equity",
    "shareholders' equity": "equity",
    "net cash provided by operating activities": "ocf",
    "net cash provided by (used in) operating activities": "ocf",
    "purchases related to property and equipment and intangible assets": "capex",
    "purchases of property and equipment and intangible assets": "capex",
    "purchases of property and equipment": "capex",
    "stock-based compensation expense": "sbc",
    "stock-based compensation": "sbc",
    "depreciation and amortization": "depreciation_amortization",
    "income before income tax": "pretax_income",
    "income before income taxes": "pretax_income",
    "income tax expense": "tax_expense",
    "income tax expense (benefit)": "tax_expense",
    "free cash flow": "company_reported_fcf",
    "principal payments on property and equipment and intangible assets": "equipment_principal_payments",
}


def cell_number(text: str) -> Decimal | None:
    text = text.strip().replace(",", "").replace("$", "").replace("%", "").replace(" ", "")
    if text in ("-", "—", "–", "--"):
        return Decimal(0)
    if not re.fullmatch(r"\(?-?\d+(?:\.\d+)?\)?", text):
        return None
    return Decimal(text.replace("(", "-").replace(")", ""))


def numeric_row(row: Tag) -> tuple[str, list[Decimal]]:
    cells = [
        c.get_text(" ", strip=True).replace("\xa0", " ")
        for c in row.find_all(["td", "th"], recursive=False)
    ]
    label = next((c for c in cells if re.search(r"[A-Za-z]", c)), "")
    if not label:
        return "", []
    tail = cells[cells.index(label) + 1 :]
    values = [v for c in tail if (v := cell_number(c)) is not None]
    return label.strip().lower().replace("’", "'"), values


def parse_release(content: bytes, fy: int, fq: int) -> dict[str, Any]:
    soup = BeautifulSoup(content, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    ordinal = ("first", "second", "third", "fourth")[fq - 1]
    title = soup.title.get_text().lower() if soup.title else ""
    if str(fy) not in title or ordinal not in title:
        raise ValueError(f"Release title does not identify FY{fy}-Q{fq}")
    end_match = re.search(r"(?:quarter|year) ended\s+([A-Za-z]+ \d{1,2},? \d{4})", text)
    if not end_match:
        raise ValueError("No official fiscal period end found")
    end = datetime.strptime(end_match[1].replace(",", ""), "%B %d %Y").date()
    start = fiscal_start(fy, fq)
    expected_end = (
        fiscal_start(fy, fq + 1) - timedelta(days=1)
        if fq < 4
        else fiscal_start(fy + 1, 1) - timedelta(days=1)
    )
    if end != expected_end:
        raise ValueError(
            f"Fiscal calendar mismatch: reported {end}, expected {expected_end}; manual review required"
        )
    date_node = soup.select_one(".article-date, time, .date")
    match = re.search(
        r"[A-Za-z]+ \d{1,2}, \d{4}", date_node.get_text(" ", strip=True) if date_node else text
    )
    if not match:
        raise ValueError("Release publication date unavailable")
    try:
        published_date = datetime.strptime(match[0], "%B %d, %Y").date()
    except ValueError:
        published_date = datetime.strptime(match[0], "%b %d, %Y").date()
    available = datetime.combine(published_date + timedelta(days=1), datetime.min.time(), ET)
    facts: dict[str, dict[str, Any]] = {}
    for index, table in enumerate(soup.find_all("table")):
        table_text = re.sub(r"\s+", " ", table.get_text(" ", strip=True)).lower()
        header = table_text[:500]
        income = "statements of income" in header or (
            "cost of revenue" in table_text
            and "income before income" in table_text
            and "non-gaap" not in table_text
        )
        balance = "balance sheets" in header or (
            "total assets" in table_text and "current assets" in table_text
        )
        cash = (
            "statements of cash flows" in header
            or "cash flows from operating activities" in table_text
            or "cash flows from financing activities" in table_text
        )
        summary = "gaap" in header and "non-gaap" not in header and index < 3
        reconciliation = (
            "reconciliation of gaap" in header or "free cash flow" in table_text
        ) and "outlook" not in header
        if not (income or balance or cash or summary or reconciliation):
            continue
        if not summary and not balance and "three months" not in header and "quarter" not in header:
            kind = "annual" if fq == 4 else "ytd"
        else:
            kind = "instant" if balance else "quarter"
        share_section = False
        for row in table.find_all("tr"):
            label, values = numeric_row(row)
            if (
                "weighted average shares" in label
                or "weighted-average shares" in label
                or "shares used in per share" in label
            ):
                share_section = True
            metric = LABELS.get(label)
            if cash and label == "cash and cash equivalents at end of period":
                metric = "cash"
            if label == "diluted" and income:
                metric = "diluted_shares" if share_section else "eps_diluted"
            if not metric or not values:
                continue
            if reconciliation and metric not in (
                "company_reported_fcf",
                "equipment_principal_payments",
            ):
                continue
            if metric in INSTANT and not balance and not (cash and metric == "cash"):
                continue
            value = values[0]
            unit = (
                "ratio"
                if metric == "gross_margin_reported"
                else "USD/shares"
                if metric == "eps_diluted"
                else "shares"
                if metric == "diluted_shares"
                else "USD"
            )
            value = (
                value / 100
                if unit == "ratio"
                else value
                if unit == "USD/shares"
                else value * 1_000_000
            )
            if metric in ("capex", "equipment_principal_payments"):
                value = abs(value)
            record = {
                "metric": metric,
                "value": value,
                "unit": unit,
                "kind": kind,
                "label": label,
                "table_index": index,
            }
            if cash and label == "cash and cash equivalents at end of period":
                record.update(metric="cash", kind="instant")
                metric = "cash"
            # Detailed statement outranks rounded summary; never overwrite quarterly with YTD.
            if metric not in facts or (
                not summary and facts[metric]["table_index"] < 2 and kind == "quarter"
            ):
                facts[metric] = record
    if "revenue" not in facts or "eps_diluted" not in facts:
        raise ValueError("Required GAAP revenue/EPS rows missing; parser schema may have changed")
    # Exact template matching only; all unmatched narrative remains in source document.
    guidance = []
    outlook = re.search(
        r"(?:Outlook\s+|NVIDIA[’']s outlook for)(.*?)\s+Highlights", text, flags=re.S
    )
    outlook_text = outlook[1] if outlook else ""
    outlook_text = re.sub(r"\s+percent\b", "%", outlook_text, flags=re.I)
    outlook_text = re.sub(r"\s+([,%])", r"\1", outlook_text)
    for metric, pattern, scale in [
        (
            "revenue",
            r"Revenue is expected to be \$\s*([\d.]+) billion, plus or minus ([\d.]+)%",
            Decimal("1e9"),
        ),
        (
            "gross_margin",
            r"GAAP and non-GAAP gross margins are expected to be ([\d.]+)%(?: and [\d.]+%, respectively)?, plus or minus ([\d.]+) basis points",
            Decimal(".01"),
        ),
        (
            "operating_expenses",
            r"GAAP(?: and non-GAAP)? operating expenses are expected to be (?:approximately )?\$\s*([\d.]+) billion",
            Decimal("1e9"),
        ),
    ]:
        found = re.search(pattern, outlook_text, re.I)
        if found:
            mid = Decimal(found[1]) * scale
            delta = Decimal(0)
            if metric == "revenue":
                delta = mid * Decimal(found[2]) / 100
            elif metric == "gross_margin":
                delta = Decimal(found[2]) / 10000
            guidance.append(
                {
                    "metric": metric,
                    "mid": mid,
                    "low": mid - delta if metric != "operating_expenses" else None,
                    "high": mid + delta if metric != "operating_expenses" else None,
                    "unit": "ratio" if metric == "gross_margin" else "USD",
                    "raw_text": found[0],
                }
            )
    tax = re.search(
        r"tax rates.*?(?:be|of)\s+(?:between\s+)?([\d.]+)%(?: and ([\d.]+)%)?(?:,? plus or minus ([\d.]+)%)?",
        outlook_text,
        re.I,
    )
    separate_tax = re.search(
        r"GAAP and non-GAAP tax rates.*?be ([\d.]+)% and ([\d.]+)%, respectively, plus or minus ([\d.]+)%",
        outlook_text,
        re.I,
    )
    if separate_tax:
        mid = Decimal(separate_tax[1]) / 100
        delta = Decimal(separate_tax[3]) / 100
        guidance.append(
            {
                "metric": "tax_rate",
                "mid": mid,
                "low": mid - delta,
                "high": mid + delta,
                "unit": "ratio",
                "raw_text": separate_tax[0],
                "target": None,
            }
        )
        tax = None
    if tax:
        mid = Decimal(tax[1]) / 100
        low = Decimal(tax[1]) / 100 if tax[2] else mid - Decimal(tax[3]) / 100 if tax[3] else None
        high = Decimal(tax[2]) / 100 if tax[2] else mid + Decimal(tax[3]) / 100 if tax[3] else None
        if low is not None and high is not None:
            mid = (low + high) / 2
        annual = bool(
            re.search(r"For the (?:full year|fiscal year)[^.]*?tax rates", outlook_text, re.I)
        )
        guidance.append(
            {
                "metric": "tax_rate",
                "mid": mid,
                "low": low,
                "high": high,
                "unit": "ratio",
                "raw_text": tax[0],
                "target": f"FY{fy}" if annual else None,
            }
        )
    segments = []
    for name in (
        "Data Center",
        "Gaming",
        "Professional Visualization",
        "Automotive",
        "OEM and Other",
        "Edge Computing",
    ):
        found = re.search(
            re.escape(name)
            + r"\s+(?:First|Second|Third|Fourth)-quarter(?: [\w ]+)? revenue (?:was|of) (?:a record )?\$\s*([\d.]+) (billion|million)",
            text,
            re.I,
        )
        if not found:
            found = re.search(
                r"(?:Record )?" + re.escape(name) + r" revenue of \$\s*([\d.]+) (billion|million)",
                text,
                re.I,
            )
        if found:
            segments.append(
                {
                    "name": name,
                    "value": Decimal(found[1])
                    * (Decimal("1e9") if found[2].lower() == "billion" else Decimal("1e6")),
                }
            )
    return {
        "facts": list(facts.values()),
        "guidance": guidance,
        "segments": segments,
        "start": start,
        "end": end,
        "available": available,
        "publication_date": str(published_date),
        "outlook": outlook_text,
    }


def ingest_release(
    db: Session,
    settings: Settings,
    content: bytes,
    url: str,
    fy: int,
    fq: int,
    *,
    observed_at: datetime | None = None,
) -> dict[str, int]:
    parsed = parse_release(content, fy, fq)
    co = company(db)
    doc = document(
        db,
        settings.qve_raw_dir,
        content,
        url=url,
        company_id=co.id,
        provider="NVIDIA IR",
        kind="Earnings Release",
        published_at=None,
        metadata={
            "publication_date": parsed["publication_date"],
            "timestamp_precision": "date",
            "availability_policy": "next_midnight_ET_upper_bound",
            "fiscal_year": fy,
            "fiscal_quarter": fq,
            **({"product_observed_at": observed_at.isoformat()} if observed_at else {}),
        },
    )
    available = parsed["available"]
    if doc.metadata_json.get("product_observed_at"):
        available = max(available, datetime.fromisoformat(doc.metadata_json["product_observed_at"]))
    if doc.metadata_json.get("changed_content"):
        available = max(available, doc.retrieved_at)
    issue(
        db,
        "publication_time_missing",
        {
            "date": parsed["publication_date"],
            "policy": "next midnight ET; exact earnings_release_timestamp remains NULL",
        },
        company_id=co.id,
        document_id=doc.id,
        period=f"FY{fy}-Q{fq}",
    )
    counts = {"created": 0, "skipped": 0}
    for fact in parsed["facts"]:
        kind = fact["kind"]
        _, added = add_fact(
            db,
            company_id=co.id,
            metric_name=fact["metric"],
            taxonomy_name="IR:" + fact["label"],
            value=fact["value"],
            unit=fact["unit"],
            period_start=None
            if kind == "instant"
            else parsed["start"]
            if kind == "quarter"
            else fiscal_start(fy, 1),
            period_end=parsed["end"],
            fiscal_year=fy,
            fiscal_quarter=fq,
            duration_kind=kind,
            reported_at=available,
            available_at=available,
            source_document_id=doc.id,
            source_priority=20,
            formula_version=VERSION,
            metadata_json={
                "table_index": fact["table_index"],
                "source_label": fact["label"],
                "publication_precision": "date",
                "share_basis": f"original_FY{fy}-Q{fq}_release",
                "period_start_method": "NVIDIA last-Sunday-January fiscal calendar; reported end checked",
            },
        )
        counts["created" if added else "skipped"] += 1
    target = f"FY{fy + 1}-Q1" if fq == 4 else f"FY{fy}-Q{fq + 1}"
    for g in parsed["guidance"]:
        key = digest([doc.id, g])
        if not db.scalar(select(GuidanceItem.id).where(GuidanceItem.identity_key == key)):
            db.add(
                GuidanceItem(
                    identity_key=key,
                    company_id=co.id,
                    fiscal_year=fy,
                    fiscal_quarter=fq,
                    guidance_for_period=g.get("target") or target,
                    metric_name=g["metric"],
                    low_value=g["low"],
                    mid_value=g["mid"],
                    high_value=g["high"],
                    unit=g["unit"],
                    guidance_type="management_outlook",
                    raw_text=g["raw_text"],
                    published_at=None,
                    available_at=available,
                    source_document_id=doc.id,
                    confidence=None,
                )
            )
    for g in parsed["segments"]:
        key = digest([doc.id, g])
        if not db.scalar(select(SegmentFact.id).where(SegmentFact.identity_key == key)):
            db.add(
                SegmentFact(
                    identity_key=key,
                    company_id=co.id,
                    fiscal_year=fy,
                    fiscal_quarter=fq,
                    segment_name=g["name"],
                    classification_kind="market_platform",
                    metric_name="revenue",
                    value=g["value"],
                    unit="USD",
                    available_at=available,
                    source_document_id=doc.id,
                )
            )
    return counts


def release_url(fy: int, fq: int) -> str:
    ordinal = ("first", "second", "third", "fourth")[fq - 1]
    suffix = f"{ordinal}-quarter-and-fiscal-{fy}" if fq == 4 else f"{ordinal}-quarter-fiscal-{fy}"
    return "https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-" + suffix


def ingest_ir(
    db: Session,
    settings: Settings,
    start_year: int = 2021,
    end_year: int = 2027,
    end_quarter: int = 2,
) -> dict[str, Any]:
    client = SourceClient()
    total: dict[str, Any] = {"created": 0, "skipped": 0, "quarters": [], "errors": []}
    for fy in range(start_year, end_year + 1):
        for fq in range(1, (end_quarter if fy == end_year else 4) + 1):
            url = release_url(fy, fq)
            content = None
            try:
                content = client.get(url)
                with db.begin_nested():
                    result = ingest_release(db, settings, content, url, fy, fq)
                for key in ("created", "skipped"):
                    total[key] += result[key]
                total["quarters"].append(f"FY{fy}-Q{fq}")
                db.commit()  # safe partial progress, source + facts atomic per quarter
            except Exception as exc:
                if content is not None:
                    document(
                        db,
                        settings.qve_raw_dir,
                        content,
                        url=url,
                        company_id=company(db).id,
                        provider="NVIDIA IR",
                        kind="Earnings Release",
                        published_at=None,
                        metadata={
                            "fiscal_year": fy,
                            "fiscal_quarter": fq,
                            "parse_status": "failed",
                        },
                    )
                error = {"quarter": f"FY{fy}-Q{fq}", "url": url, "error": str(exc)}
                total["errors"].append(error)
                issue(
                    db,
                    "source_unavailable_or_parse_error",
                    error,
                    company_id=company(db).id,
                    period=f"FY{fy}-Q{fq}",
                )
                db.commit()
    return total


def replay_ir_cache(db: Session, settings: Settings, manifest_path) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Reparse verified cached bytes offline; manifest contains URLs, periods and hashes."""
    import hashlib
    import json
    from pathlib import Path

    manifest_path = Path(manifest_path)
    result: dict[str, Any] = {"created": 0, "skipped": 0, "quarters": [], "errors": []}
    for entry in json.loads(manifest_path.read_text()):
        path = manifest_path.parent / entry["raw_path"]
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise ValueError(f"Raw source hash mismatch: {path}")
        r = ingest_release(
            db, settings, content, entry["url"], entry["fiscal_year"], entry["fiscal_quarter"]
        )
        for key in ("created", "skipped"):
            result[key] += r[key]
        result["quarters"].append(f"FY{entry['fiscal_year']}-Q{entry['fiscal_quarter']}")
    return result
