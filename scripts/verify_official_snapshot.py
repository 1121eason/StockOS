"""Compare stored figures to independently transcribed official-source check values."""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.config import Settings
from valuation_engine.db.schema import GuidanceItem, SegmentFact
from valuation_engine.db.session import engine
from valuation_engine.db.store import company
from valuation_engine.normalization.quarterly import PointInTimeRepository

root = Path(__file__).resolve().parents[1]
expected = json.loads((root / "tests/fixtures/nvda_fy2027q2_verified.json").read_text())
with Session(engine(Settings().qve_database_url)) as db:
    co = company(db)
    q = PointInTimeRepository(db, co.id).quarter(
        2027, 2, datetime.fromisoformat("2026-08-27T09:30:00-04:00")
    )
    assert q is not None
    checks = []
    for metric, number in {**expected["reported"], "fcf": expected["engine_fcf"]}.items():
        actual = q.value(metric)
        checks.append(
            {
                "metric": metric,
                "expected": number,
                "actual": str(actual),
                "pass": actual == Decimal(number),
            }
        )
    segment = db.scalar(
        select(SegmentFact).where(
            SegmentFact.company_id == co.id,
            SegmentFact.fiscal_year == 2027,
            SegmentFact.fiscal_quarter == 2,
            SegmentFact.segment_name == "Data Center",
        )
    )
    checks.append(
        {
            "metric": "Data Center revenue (rounded source)",
            "pass": segment is not None
            and segment.value == Decimal(expected["data_center_revenue_rounded"]),
        }
    )
    for metric in ("revenue", "gross_margin"):
        g = db.scalar(
            select(GuidanceItem).where(
                GuidanceItem.company_id == co.id,
                GuidanceItem.fiscal_year == 2027,
                GuidanceItem.fiscal_quarter == 2,
                GuidanceItem.metric_name == metric,
            )
        )
        for point in ("low", "mid", "high"):
            actual = getattr(g, point + "_value") if g else None
            checks.append(
                {
                    "metric": f"guidance_{metric}_{point}",
                    "pass": actual
                    == Decimal(expected["next_quarter_guidance"][metric + "_" + point]),
                }
            )
    result = {
        "source": expected["source_url"],
        "checks": checks,
        "passed": sum(c["pass"] for c in checks),
        "total": len(checks),
    }
    (root / "data/manual-validation.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    if not all(c["pass"] for c in checks):
        raise SystemExit(1)
