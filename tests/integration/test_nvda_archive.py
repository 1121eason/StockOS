"""Actual archived NVIDIA regression checks; the PM gate report separately requires cap/EV."""

import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from valuation_engine.db.session import engine
from valuation_engine.hardening.basis import get_price_as_reported
from valuation_engine.normalization.quarterly import PointInTimeRepository, prior_period


@pytest.mark.parametrize(
    "fy,fq,published,opening,expected_price,expected_eps",
    [
        (2022, 1, "2021-05-26T16:20:00-04:00", "2021-05-27T09:30:00-04:00", "627.99", "8.45"),
        (2024, 1, "2023-05-24T16:20:00-04:00", "2023-05-25T09:30:00-04:00", "385.23", "1.92"),
        (2027, 2, "2026-08-26T16:20:00-04:00", "2026-08-27T09:30:00-04:00", "222.86", "7.91"),
    ],
)
def test_archived_nvda_visibility_and_historical_pe(
    fy, fq, published, opening, expected_price, expected_eps
):
    url = os.environ.get("QVE_TEST_POSTGRES_URL")
    if not url and not Path("data/m11/report/summary.json").exists():
        pytest.skip("Actual archive bundle is not installed; synthetic contracts run independently")
    with Session(engine(url or "sqlite:///data/qve.db")) as db:
        repo = PointInTimeRepository(db, 1)
        release = datetime.fromisoformat(published)
        at = datetime.fromisoformat(opening)
        assert repo.quarter(fy, fq, release - timedelta(microseconds=1)) is None
        assert repo.quarter(fy, fq, release + timedelta(seconds=59)) is None
        assert repo.quarter(fy, fq, release + timedelta(minutes=1)).value("revenue") > 0
        qs = [repo.quarter(*prior_period(fy, fq, n), at) for n in range(4)]
        eps = sum(repo.normalize_eps(q.metrics["eps_diluted"], at.date()) for q in qs)
        assert eps == Decimal(expected_eps)
        price = get_price_as_reported(db, 1, at)
        assert price["available_at"] == at
        assert price["provenance"]["original_response_hash"]
        assert abs(price["value"] - Decimal(expected_price)) < Decimal(".00002")
        assert abs(
            price["value"] / eps - Decimal(expected_price) / Decimal(expected_eps)
        ) < Decimal(".00001")
