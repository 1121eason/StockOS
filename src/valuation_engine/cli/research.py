"""Human-readable M2 commands with optional full-provenance JSON."""

import json
from datetime import datetime

import typer
from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.config import Settings
from valuation_engine.db.schema import ForecastRun, ResearchValuation
from valuation_engine.db.session import engine
from valuation_engine.research.history import replay
from valuation_engine.research.inputs import FinancialInputs
from valuation_engine.research.numbers import D, canonical
from valuation_engine.research.service import MODELS, build_forecast, revisions, stored_periods
from valuation_engine.research.valuation import build_valuation
from valuation_engine.time import ET, aware, now


def at_time(value):
    return aware(datetime.fromisoformat(value.replace("Z", "+00:00"))) if value else now()


def require_ticker(ticker):
    if ticker != "NVDA":
        raise typer.BadParameter("M2 benchmark supports NVDA only")


def emit(value):
    typer.echo(json.dumps(canonical(value), indent=2, sort_keys=True))


def fmt(value, percent=False):
    if value is None:
        return "unavailable"
    x = D(str(value))
    return f"{x * 100:,.2f}%" if percent else f"{x:,.4f}"


def forecast_command(ticker="NVDA", as_of=None, model="A", checkpoint=None, json_output=False):
    require_ticker(ticker)
    settings = Settings()
    at = at_time(as_of)
    with Session(engine(settings.qve_database_url)) as db:
        data = FinancialInputs(db, 1, at)
        kind = checkpoint or ("first_tradable" if at == data.tradable_at else "research_replay")
        run = build_forecast(db, 1, at, kind, model, data)
        rev = revisions(db, run)
        periods = stored_periods(db, run.id)
        result = dict(
            run={c.name: getattr(run, c.name) for c in run.__table__.columns},
            periods=periods,
            revision=rev,
        )
        db.commit()
        if json_output:
            emit(result)
            return
        typer.echo(
            f"NVDA | {kind} | {at.astimezone(ET).isoformat()}\n{run.model_name} / {run.model_version}\nresearch_reconstructed_internal | GAAP\n"
        )
        q = next(r for r in periods if r["period_type"] == "quarter")
        raw = run.metadata_json["raw_guidance"].get("revenue", {}).get("midpoint")
        typer.echo(
            f"Q+1 Revenue — raw guidance: {fmt(raw)}; forecast: {fmt(q['revenue'])}\nQ+1 Gross Margin: {fmt(q['gross_margin'], True)}\nQ+1 GAAP OpEx: {fmt(q['operating_expenses'])}"
        )
        for horizon in ("NTM", "FY1", "FY2"):
            row = next(r for r in periods if r["period_type"] == horizon)
            typer.echo(
                f"{horizon} (FY{row['fiscal_year']}) — Revenue {fmt(row['revenue'])} | EPS {fmt(row['eps'])} | FCF {fmt(row['free_cash_flow'])}"
            )
        for change in rev.get("comparisons", []):
            if change["new_label"] == "FY1":
                eps = change["metrics"]["eps"]
                typer.echo(
                    f"FY1 EPS revision, same {change['target']}: {fmt(eps['previous'])} → {fmt(eps['current'])}; {fmt(eps['percentage_revision'], True)} (prior label: {change['previous_label']})"
                )
        band = q["metadata_json"]["intervals"]["revenue"]
        typer.echo(
            f"Q+1 revenue interval: {band['status']}; historical sample {band['sample_count']}; P80 {fmt(band['lower'])} to {fmt(band['upper'])}\nUse --json-output for all assumptions and provenance."
        )


def valuation_command(ticker="NVDA", as_of=None, model="A", json_output=False, section=None):
    require_ticker(ticker)
    settings = Settings()
    requested = at_time(as_of)
    with Session(engine(settings.qve_database_url)) as db:
        data = FinancialInputs(db, 1, requested)
        at = data.tradable_at
        if at > requested:
            raise typer.BadParameter(
                "The first permitted trade has not occurred at the requested cutoff"
            )
        if as_of is not None and requested != at:
            raise typer.BadParameter(
                f"M2 historical valuation uses first-tradable checkpoints; use --as-of {at.isoformat()}"
            )
        run = build_forecast(db, 1, at, "first_tradable", model)
        value = build_valuation(db, run)
        result = {c.name: getattr(value, c.name) for c in value.__table__.columns}
        db.commit()
        if json_output:
            emit(result)
            return
        m = value.metadata_json
        typer.echo(
            f"NVDA | First Tradable | {at.astimezone(ET).isoformat()}\nresearch_reconstructed_internal / {value.valuation_model_version}\nPrice {fmt(m['price'])} | Market Cap {fmt(m['market_cap'])}"
        )
        if section is None:
            typer.echo(
                f"NTM P/E {fmt(value.ntm_pe)} | FY1 P/E {fmt(value.fy1_pe)} | FY2 P/E {fmt(value.fy2_pe)}\nForward FCF Yield {fmt(value.forward_fcf_yield, True)}\nPrior-history NTM P/E percentile {fmt(value.historical_ntm_pe_percentile, True)}"
            )
        if section != "reverse":
            typer.echo(
                f"DCF sensitivity low/base/high: {fmt(value.dcf_low)} / {fmt(value.dcf_base)} / {fmt(value.dcf_high)}\nFCFF is an explicit NOPAT cash-conversion proxy; sensitivity bounds are not confidence intervals."
            )
        if section != "dcf":
            typer.echo(
                f"Reverse DCF implied 5Y FCFF CAGR {fmt(value.reverse_dcf_implied_fcf_cagr, True)}\nInternal 5Y FCFF CAGR {fmt(value.internal_fcf_cagr, True)}\nExpectations Gap {fmt(value.expectations_gap * 100) if value.expectations_gap is not None else 'unavailable'} percentage points\nReverse solver status: {m['reverse_dcf']['status']}"
            )


def register(app):
    @app.command("forecast-history")
    def forecast_history(ticker: str = "NVDA", as_of: str | None = None, json_output: bool = False):
        require_ticker(ticker)
        with Session(engine(Settings().qve_database_url)) as db:
            result = replay(
                db, at_time(as_of), progress=lambda q: typer.echo(f"Replayed {q}", err=True)
            )
            if json_output:
                emit(result)
            else:
                typer.echo(
                    f"{len(result['runs'])} immutable forecast runs; A/B/C; two checkpoints; research_reconstructed_internal"
                )

    @app.command("forecast-revisions")
    def forecast_revisions(ticker: str = "NVDA", model: str = "A"):
        require_ticker(ticker)
        with Session(engine(Settings().qve_database_url)) as db:
            runs = list(
                db.scalars(
                    select(ForecastRun)
                    .where(
                        ForecastRun.forecast_type == "first_tradable",
                        ForecastRun.model_name == MODELS[model],
                    )
                    .order_by(ForecastRun.forecast_as_of)
                )
            )
            result = [revisions(db, r) for r in runs]
            db.commit()
            emit(result)

    @app.command("forecast-accuracy")
    def forecast_accuracy(ticker: str = "NVDA", as_of: str | None = None):
        from valuation_engine.evaluation.forecasts import evaluate

        require_ticker(ticker)
        settings = Settings()
        with (
            Session(engine(settings.qve_database_url)) as db,
            Session(engine(settings.qve_label_database_url)) as labels,
        ):
            result = evaluate(db, labels, at_time(as_of))
            labels.commit()
            emit(result)

    @app.command("valuation")
    def valuation(
        ticker: str = "NVDA", as_of: str | None = None, model: str = "A", json_output: bool = False
    ):
        valuation_command(ticker, as_of, model, json_output)

    @app.command("valuation-history")
    def valuation_history(ticker: str = "NVDA", as_of: str | None = None):
        require_ticker(ticker)
        with Session(engine(Settings().qve_database_url)) as db:
            replay(db, at_time(as_of))
            emit(
                [
                    {c.name: getattr(row, c.name) for c in row.__table__.columns}
                    for row in db.scalars(
                        select(ResearchValuation).order_by(
                            ResearchValuation.as_of_timestamp, ResearchValuation.id
                        )
                    )
                ]
            )

    @app.command("dcf")
    def dcf(ticker: str = "NVDA", as_of: str | None = None, json_output: bool = False):
        valuation_command(ticker, as_of, "A", json_output, "dcf")

    @app.command("reverse-dcf")
    def reverse_dcf(ticker: str = "NVDA", as_of: str | None = None, json_output: bool = False):
        valuation_command(ticker, as_of, "A", json_output, "reverse")
