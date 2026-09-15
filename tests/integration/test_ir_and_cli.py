from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from valuation_engine.cli.main import app, migrate
from valuation_engine.config import Settings
from valuation_engine.db.schema import FinancialFact, GuidanceItem, SourceDocument
from valuation_engine.ingestion.ir import ingest_release, parse_release
from valuation_engine.normalization.quarterly import PointInTimeRepository


@pytest.fixture
def html():
    return b"""<html><title>NVIDIA Announces Financial Results for Second Quarter Fiscal 2027</title>
    <div class="article-date">August 26, 2026</div><p>second quarter ended July&nbsp;26, 2026</p>
    <table><tr><td>GAAP Q2 FY27</td></tr><tr><td>Revenue</td><td>100</td></tr><tr><td>Diluted earnings per share</td><td>1.25</td></tr></table>
    <table><tr><td>CONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS Three Months Ended Six Months Ended</td></tr>
    <tr><td>Net cash provided by operating activities</td><td>30</td><td>70</td></tr>
    <tr><td>Purchases related to property and equipment and intangible assets</td><td>(5)</td><td>(15)</td></tr></table>
    <p>Outlook Revenue is expected to be $108.0 billion, plus or minus 2%. GAAP and non-GAAP gross margins are expected to be 74.0%, plus or minus 50 basis points. Highlights</p>
    </html>"""


def test_ir_quarter_not_ytd_and_guidance(db, tmp_path, html):
    settings = Settings(qve_raw_dir=tmp_path / "raw")
    a = ingest_release(db, settings, html, "https://example.test/release", 2027, 2)
    b = ingest_release(db, settings, html, "https://example.test/release", 2027, 2)
    assert a["created"] == 4 and b["created"] == 0 and b["skipped"] == 4
    assert db.scalar(select(func.count()).select_from(SourceDocument)) == 1
    repo = PointInTimeRepository(db, 1)
    assert repo.quarter(2027, 2, datetime.fromisoformat("2026-08-26T23:59:59-04:00")) is None
    q = repo.quarter(2027, 2, datetime.fromisoformat("2026-08-27T00:00:00-04:00"))
    assert q.value("ocf") == Decimal(30_000_000)
    assert q.value("capex") == Decimal(5_000_000)
    assert q.value("fcf") == Decimal(25_000_000)
    g = db.scalar(select(GuidanceItem).where(GuidanceItem.metric_name == "revenue"))
    assert g.low_value == Decimal(105_840_000_000)
    assert g.high_value == Decimal(110_160_000_000)
    assert db.scalar(select(FinancialFact)).earnings_release_timestamp is None


def test_parser_rejects_wrong_quarter(html):
    with pytest.raises(ValueError, match="title"):
        parse_release(html, 2027, 1)


def test_migrations_and_cli(tmp_path, monkeypatch):
    core = f"sqlite:///{tmp_path}/core.db"
    labels = f"sqlite:///{tmp_path}/labels.db"
    monkeypatch.setenv("QVE_DATABASE_URL", core)
    monkeypatch.setenv("QVE_LABEL_DATABASE_URL", labels)
    runner = CliRunner()
    result = runner.invoke(app, ["init-db"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["init-db"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["coverage"])
    assert result.exit_code == 0 and "FY2027-Q2" in result.output
    result = runner.invoke(
        app, ["show-quarter", "--quarter", "FY2027-Q2", "--as-of", "2026-08-27T09:30:00-04:00"]
    )
    assert result.exit_code == 2 and "unavailable" in result.output


def test_reject_same_label_database(tmp_path):
    url = f"sqlite:///{tmp_path}/same.db"
    with pytest.raises(ValueError, match="different"):
        migrate(Settings(qve_database_url=url, qve_label_database_url=url))


def test_guidance_annual_tax_and_approximate_opex(html):
    modified = html.replace(
        b" Highlights",
        b" GAAP and non-GAAP operating expenses are expected to be approximately $9.2 billion. For the full year fiscal 2027, NVIDIA expects GAAP and non-GAAP tax rates to be between 16.0% and 18.0%. Highlights",
    )
    parsed = parse_release(modified, 2027, 2)
    tax = next(g for g in parsed["guidance"] if g["metric"] == "tax_rate")
    op = next(g for g in parsed["guidance"] if g["metric"] == "operating_expenses")
    assert tax["target"] == "FY2027" and tax["mid"] == Decimal(".17")
    assert op["low"] is None and op["high"] is None


def test_cashflow_table_with_heading_outside_table(html):
    modified = html.replace(b"CONDENSED CONSOLIDATED STATEMENTS OF CASH FLOWS ", b"")
    modified = modified.replace(
        b"<tr><td>Net cash",
        b"<tr><td>Cash flows from operating activities:</td></tr><tr><td>Net cash",
    )
    parsed = parse_release(modified, 2027, 2)
    assert next(f for f in parsed["facts"] if f["metric"] == "ocf")["value"] == Decimal(30_000_000)
