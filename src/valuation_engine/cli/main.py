import json
import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from valuation_engine.config import Settings
from valuation_engine.db.schema import DataQualityIssue, FinancialFact, IngestionRun, SourceDocument
from valuation_engine.db.session import engine
from valuation_engine.db.store import company, issue
from valuation_engine.features.engine import compute, persist
from valuation_engine.forecasts.baseline import forecast
from valuation_engine.ingestion.ir import ingest_ir
from valuation_engine.ingestion.market import YahooChartProvider, ingest_prices
from valuation_engine.ingestion.sec import ingest_sec
from valuation_engine.logging import log
from valuation_engine.normalization.quarterly import PointInTimeRepository
from valuation_engine.time import ET, aware, now
from valuation_engine.validation import validate_quarter
from valuation_engine.valuation.ratios import value_at

app = typer.Typer(
    help="Point-in-time NVIDIA fundamental valuation engine. M1 research, no trading signals."
)


def output(value: Any) -> None:
    typer.echo(json.dumps(value, indent=2, default=str, sort_keys=True))


def cutoff(value: str | None) -> datetime:
    return aware(datetime.fromisoformat(value.replace("Z", "+00:00"))) if value else now()


def migrate(settings: Settings) -> None:
    if settings.qve_database_url == settings.qve_label_database_url:
        raise ValueError("Feature and label database URLs must be different")
    Path("data").mkdir(exist_ok=True)
    root = Path(__file__).resolve().parents[3]
    for labels, url in (
        (False, settings.qve_database_url),
        (True, settings.qve_label_database_url),
    ):
        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        cfg.attributes["labels"] = labels
        if labels:
            cfg.set_main_option("version_locations", str(root / "migrations/labels"))
        command.upgrade(cfg, "head")


@app.command("init-db")
def init_db() -> None:
    migrate(Settings())
    output({"status": "migrated", "feature_label_databases": "separate"})


def run_ingestion(provider: str, callback: Callable[[Session, Settings], dict[str, Any]]) -> None:
    settings = Settings()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with Session(engine(settings.qve_database_url)) as db:
        run = IngestionRun(provider=provider, status="running", code_version="0.1.1")
        db.add(run)
        db.commit()
        run_id = run.id
        log("ingestion_start", source=provider, run_id=run_id)
        try:
            result = callback(db, settings)
            refreshed = db.get(IngestionRun, run_id)
            assert refreshed is not None
            run = refreshed
            assert run is not None
            run.records_created = result.get("created", 0)
            run.records_skipped = result.get("skipped", 0)
            run.errors = result.get("errors", [])
            run.status = "partial" if run.errors else "completed"
            run.completed_at = now()
            db.commit()
            log("ingestion_complete", source=provider, status=run.status, **result)
            output(result)
            if run.status == "partial":
                raise typer.Exit(2)
        except typer.Exit:
            raise
        except Exception as exc:
            db.rollback()
            refreshed = db.get(IngestionRun, run_id)
            assert refreshed is not None
            run = refreshed
            assert run is not None
            run.status = "failed"
            run.errors = [str(exc)]
            run.completed_at = now()
            issue(
                db, "ingestion_failure", {"provider": provider, "error": str(exc)}, severity="error"
            )
            db.commit()
            log("ingestion_failed", source=provider, error=str(exc))
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc


@app.command("ingest-sec")
def sec(ticker: str = "NVDA") -> None:
    if ticker != "NVDA":
        raise typer.BadParameter("NVDA only")
    run_ingestion("SEC", ingest_sec)


@app.command("configure-sec")
def configure_sec() -> None:
    """Save SEC's public download identification locally; never an API credential."""
    import os
    import re

    organization = typer.prompt("Project or organization", default="StockOS Research")
    email = typer.prompt("Contact email sent to SEC with downloads")
    identity = f"{organization.strip()} {email.strip()}"
    Settings(sec_user_agent=identity).require_sec_identity()
    path = Path(".env")
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [line for line in lines if not re.match(r"\s*SEC_USER_AGENT\s*=", line)]
    lines.append("SEC_USER_AGENT=" + json.dumps(identity))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    output({"configured": True, "location": ".env", "identity_in_logs": False})


@app.command("reconcile-sec-ir")
def reconcile_sources() -> None:
    from valuation_engine.hardening.reconcile import reconcile

    with Session(engine(Settings().qve_database_url)) as db:
        result = reconcile(db, company(db).id)
        db.commit()
        output(result)


@app.command("guidance-coverage")
def guidance_matrix() -> None:
    from valuation_engine.hardening.guidance import guidance_coverage

    with Session(engine(Settings().qve_database_url)) as db:
        output(guidance_coverage(db, company(db).id))


@app.command("known-shares")
def known_shares(
    as_of: Annotated[str, typer.Option()], basis_date: Annotated[str | None, typer.Option()] = None
) -> None:
    from datetime import date

    from valuation_engine.hardening.shares import get_latest_known_shares

    with Session(engine(Settings().qve_database_url)) as db:
        output(
            get_latest_known_shares(
                db,
                company(db).id,
                cutoff(as_of),
                basis_date=date.fromisoformat(basis_date) if basis_date else None,
            )
        )


@app.command("ingest-nvda-ir")
def ir(start_year: int = 2021, end_year: int = 2027, end_quarter: int = 2) -> None:
    run_ingestion(
        "NVIDIA IR", lambda db, settings: ingest_ir(db, settings, start_year, end_year, end_quarter)
    )


@app.command("ingest-prices")
def prices(start: str = "2020-01-01", end: str | None = None) -> None:
    run_ingestion(
        "Yahoo Chart",
        lambda db, _: ingest_prices(
            db,
            YahooChartProvider(),
            date.fromisoformat(start),
            date.fromisoformat(end) if end else now().date(),
        ),
    )


@app.command("replay-ir-cache")
def replay_cache(manifest: Annotated[Path, typer.Option()]) -> None:
    from valuation_engine.ingestion.ir import replay_ir_cache

    run_ingestion(
        "NVIDIA IR cached bytes", lambda db, settings: replay_ir_cache(db, settings, manifest)
    )


def all_quarters(db: Session, co_id: int) -> list[tuple[int, int]]:
    return list(
        db.execute(
            select(FinancialFact.fiscal_year, FinancialFact.fiscal_quarter)
            .where(FinancialFact.company_id == co_id)
            .distinct()
            .order_by(FinancialFact.fiscal_year, FinancialFact.fiscal_quarter)
        ).tuples()
    )


@app.command("build-quarterly-snapshots")
def build(ticker: str = "NVDA", as_of: str | None = None) -> None:
    settings = Settings()
    with Session(engine(settings.qve_database_url)) as db:
        co = company(db, ticker)
        repo = PointInTimeRepository(db, co.id)
        made = []
        for fy, fq in all_quarters(db, co.id):
            q = repo.quarter(fy, fq, cutoff(as_of))
            if q and q.metrics:
                row = repo.save(q)
                made.append(
                    {
                        "quarter": f"FY{fy}-Q{fq}",
                        "snapshot_id": row.id,
                        "metrics": len(q.metrics),
                        "missing": q.missing,
                    }
                )
        db.commit()
        output(made)


@app.command("calculate-features")
def features(ticker: str = "NVDA", as_of: str | None = None) -> None:
    settings = Settings()
    timestamp = cutoff(as_of)
    with Session(engine(settings.qve_database_url)) as db:
        co = company(db, ticker)
        repo = PointInTimeRepository(db, co.id)
        count = 0
        for fy, fq in all_quarters(db, co.id):
            q = repo.quarter(fy, fq, timestamp)
            if q and q.metrics:
                persist(db, repo.save(q), compute(repo, q))
                count += 1
        db.commit()
        output({"quarters": count, "as_of": timestamp})


@app.command("validate-data")
def validate(ticker: str = "NVDA", as_of: str | None = None) -> None:
    settings = Settings()
    timestamp = cutoff(as_of)
    with Session(engine(settings.qve_database_url)) as db:
        co = company(db, ticker)
        repo = PointInTimeRepository(db, co.id)
        total = {"quarters": 0, "checked": 0, "failed": 0, "missing": 0}
        for fy, fq in all_quarters(db, co.id):
            q = repo.quarter(fy, fq, timestamp)
            if q:
                r = validate_quarter(db, q)
                total["quarters"] += 1
                for k, v in r.items():
                    total[k] += v
        db.commit()
        output(total)
        if total["failed"]:
            raise typer.Exit(2)


def parse_quarter(value: str) -> tuple[int, int]:
    import re

    match = re.fullmatch(r"FY(\d{4})-Q([1-4])", value)
    if not match:
        raise typer.BadParameter("Expected FY2027-Q2")
    return int(match[1]), int(match[2])


@app.command("show-quarter")
def show(
    quarter: str = typer.Option(...),
    ticker: str = "NVDA",
    as_of: str | None = None,
    json_output: bool = False,
) -> None:
    settings = Settings()
    with Session(engine(settings.qve_database_url)) as db:
        co = company(db, ticker)
        repo = PointInTimeRepository(db, co.id)
        q = repo.quarter(*parse_quarter(quarter), cutoff(as_of))
        if not q:
            typer.echo("unavailable / no facts known at cutoff")
            raise typer.Exit(2)
        f = compute(repo, q)
        fact_ids = {i for obs in q.metrics.values() for i in obs.fact_ids}
        docs = db.scalars(
            select(SourceDocument)
            .join(FinancialFact, FinancialFact.source_document_id == SourceDocument.id)
            .where(FinancialFact.id.in_(fact_ids))
            .distinct()
        ).all()
        from valuation_engine.db.schema import GuidanceItem, SegmentFact

        guidance = db.scalars(
            select(GuidanceItem).where(
                GuidanceItem.company_id == co.id,
                GuidanceItem.fiscal_year == q.fiscal_year,
                GuidanceItem.fiscal_quarter == q.fiscal_quarter,
                GuidanceItem.available_at <= q.as_of,
            )
        ).all()
        segments = db.scalars(
            select(SegmentFact).where(
                SegmentFact.company_id == co.id,
                SegmentFact.fiscal_year == q.fiscal_year,
                SegmentFact.fiscal_quarter == q.fiscal_quarter,
                SegmentFact.available_at <= q.as_of,
            )
        ).all()
        data = {
            "quarter": q.model_dump(mode="json"),
            "features": f.values,
            "feature_metadata": f.metadata,
            "anomalies": f.anomalies,
            "guidance": [
                {
                    "metric": g.metric_name,
                    "target": g.guidance_for_period,
                    "low": g.low_value,
                    "mid": g.mid_value,
                    "high": g.high_value,
                    "source_document_id": g.source_document_id,
                }
                for g in guidance
            ],
            "segments": [
                {"name": g.segment_name, "value": g.value, "unit": g.unit} for g in segments
            ],
            "sources": [
                {
                    "id": d.id,
                    "provider": d.source_provider,
                    "url": d.source_url,
                    "sha256": d.content_hash,
                }
                for d in docs
            ],
        }
        if json_output:
            output(data)
            return
        typer.echo(f"NVDA {quarter} | as known {q.as_of.astimezone(ET).isoformat()}")
        typer.echo(f"Period {q.period_start} to {q.period_end} | {q.selection_policy}")
        for name, obs in sorted(q.metrics.items()):
            typer.echo(
                f"{name:32} {obs.value:>22,.4f} {obs.unit} | available {obs.available_at.astimezone(ET).isoformat()}"
            )
        typer.echo("\nFeatures / Guidance / Anomalies / Sources")
        output({k: v for k, v in data.items() if k not in ("quarter", "feature_metadata")})


@app.command("forecast")
def forecast_command(
    quarter: str | None = None,
    as_of: str | None = None,
    ticker: str = "NVDA",
    model: str = "A",
    checkpoint: str | None = None,
    json_output: bool = False,
) -> None:
    if quarter is None:
        from valuation_engine.cli.research import forecast_command as research_forecast

        research_forecast(ticker, as_of, model, checkpoint, json_output)
        return
    settings = Settings()
    timestamp = cutoff(as_of)
    with Session(engine(settings.qve_database_url)) as db:
        co = company(db)
        repo = PointInTimeRepository(db, co.id)
        q = repo.quarter(*parse_quarter(quarter), timestamp)
        if not q:
            raise typer.BadParameter("Quarter unavailable at cutoff")
        row = forecast(db, repo.save(q), timestamp)
        db.commit()
        output(
            {
                "id": row.id,
                "forecast_as_of": row.forecast_as_of,
                "fiscal_period": row.fiscal_period,
                "revenue": row.revenue,
                "eps": row.eps,
                "fcf": row.fcf,
                "generated_kind": row.generated_kind,
                "assumption_set_id": row.assumption_set_id,
            }
        )


@app.command("value-quarter")
def valuation(quarter: str = typer.Option(...), as_of: str | None = None) -> None:
    settings = Settings()
    timestamp = cutoff(as_of)
    with Session(engine(settings.qve_database_url)) as db:
        repo = PointInTimeRepository(db, company(db).id)
        q = repo.quarter(*parse_quarter(quarter), timestamp)
        if not q:
            raise typer.BadParameter("Quarter unavailable at cutoff")
        row = value_at(db, repo, q, timestamp)
        db.commit()
        output({c.name: getattr(row, c.name) for c in row.__table__.columns})


@app.command("coverage")
def coverage() -> None:
    settings = Settings()
    with Session(engine(settings.qve_database_url)) as db:
        co = company(db)
        quarters = all_quarters(db, co.id)
        expected = [
            (fy, fq) for fy in range(2021, 2028) for fq in range(1, (2 if fy == 2027 else 4) + 1)
        ]
        issues = db.execute(
            select(DataQualityIssue.issue_type, func.count()).group_by(DataQualityIssue.issue_type)
        ).all()
        output(
            {
                "quarters": [f"FY{fy}-Q{fq}" for fy, fq in quarters],
                "missing_quarters": [
                    f"FY{fy}-Q{fq}" for fy, fq in expected if (fy, fq) not in quarters
                ],
                "facts": db.scalar(select(func.count()).select_from(FinancialFact)),
                "source_documents": db.scalar(select(func.count()).select_from(SourceDocument)),
                "issues": {k: v for k, v in issues},
            }
        )


@app.command("build-labels")
def labels(as_of: str | None = None) -> None:
    from valuation_engine.backtest.labels import build_outcome

    settings = Settings()
    if settings.qve_database_url == settings.qve_label_database_url:
        raise typer.BadParameter("Labels require separate database")
    with (
        Session(engine(settings.qve_database_url)) as db,
        Session(engine(settings.qve_label_database_url)) as label_db,
    ):
        co = company(db)
        count = 0
        releases = db.execute(
            select(
                FinancialFact.fiscal_year,
                FinancialFact.fiscal_quarter,
                func.min(FinancialFact.available_at),
            )
            .where(FinancialFact.company_id == co.id)
            .group_by(FinancialFact.fiscal_year, FinancialFact.fiscal_quarter)
        ).all()
        for _fy, _fq, at in releases:
            if build_outcome(db, label_db, co.id, at, cutoff(as_of)):
                count += 1
        label_db.commit()
        output({"label_rows": count})


from valuation_engine.cli.research import register as register_research_commands  # noqa: E402

register_research_commands(app)

from valuation_engine.cli.regime import register as register_regime_commands  # noqa: E402

register_regime_commands(app)

from valuation_engine.cli.ai import register as register_ai  # noqa: E402

register_ai(app)
