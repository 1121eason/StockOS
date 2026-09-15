"""Bind normalized vendor bars to a retained original response; reject changed prices."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.config import Settings
from valuation_engine.db.schema import CorporateAction, MarketPrice
from valuation_engine.db.store import document


def import_price_archive(db: Session, settings: Settings, manifest: Path) -> tuple[int, list[int]]:
    item = json.loads(manifest.read_text())
    raw = Path(item["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != item["hash"]:
        raise ValueError("Market archive hash mismatch")
    result = json.loads(raw)["chart"]["result"][0]
    if result["meta"]["symbol"] != "NVDA":
        raise ValueError("Unexpected market archive ticker")
    lookup = {datetime.fromtimestamp(t, UTC).date(): i for i, t in enumerate(result["timestamp"])}
    expected_actions = {
        (a.split_date, a.ratio_numerator / a.ratio_denominator)
        for a in db.scalars(select(CorporateAction).where(CorporateAction.company_id == 1))
        if min(lookup) <= a.split_date <= max(lookup)
    }
    vendor_actions = {
        (
            datetime.fromtimestamp(e["date"], UTC).date(),
            Decimal(str(e["numerator"])) / Decimal(str(e["denominator"])),
        )
        for e in result.get("events", {}).get("splits", {}).values()
    }
    if expected_actions != vendor_actions:
        raise ValueError(
            "Vendor split events disagree with official corporate actions; basis cannot be inferred safely"
        )
    values = result["indicators"]["quote"][0]
    matched = []
    for bar in db.scalars(select(MarketPrice).where(MarketPrice.provider == "Yahoo Chart")):
        i = lookup.get(bar.timestamp.date())
        if i is None:
            continue
        for field in ("open", "high", "low", "close"):
            # SQL legacy columns are decimal to 8 places. Compare only the declared precision.
            if abs(getattr(bar, field) - Decimal(str(values[field][i]))) > Decimal(".00000002"):
                raise ValueError(
                    f"Vendor price revision for bar {bar.id}, {field}; retain and reconcile before reuse"
                )
        matched.append(bar.id)
    doc = document(
        db,
        settings.qve_raw_dir,
        raw,
        url=item["url"],
        company_id=1,
        provider="Yahoo Chart",
        kind="Original market data response",
        published_at=None,
        metadata={
            "matched_market_price_ids": matched,
            "retrieved_at_from_fetch": item["retrieved_at"],
            "provider_basis": "split_adjusted_current_vintage",
            "validation": "all OHLC within stored 8-decimal precision",
            "vendor_split_events": result.get("events", {}).get("splits", {}),
        },
    )
    return doc.id, matched
