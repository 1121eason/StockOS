"""AI research CLI and isolated, read-only combined Quant/Regime/AI presentation."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.ai.antigravity_provider import AntigravityCLIProvider
from valuation_engine.ai.cli_provider import (
    CapabilityCLIProvider,
    ClaudeCLIProvider,
    CodexCLIProvider,
    GeminiCLIProvider,
)
from valuation_engine.ai.provider import OpenAIProvider, RecordedProvider
from valuation_engine.ai.service import analyze, prepare
from valuation_engine.cli.research import at_time, emit, require_ticker
from valuation_engine.config import Settings
from valuation_engine.db.schema import (
    AIAnalysisRun,
    AIAnalystFeature,
    AIAnalystSnapshot,
    AIChallenge,
    AIEvidence,
    AIHumanReview,
    ResearchValuation,
)
from valuation_engine.db.session import engine
from valuation_engine.quant.ai_context import context_for, resolve_run


def build_provider(settings, recorded=None, name=None):
    if recorded:
        return RecordedProvider(Path(recorded))
    selected = name or settings.qve_ai_provider or "claude_cli"
    model: CapabilityCLIProvider
    if selected in {"claude_cli", "antigravity_cli", "gemini_cli", "codex_cli"}:
        if selected == "claude_cli":
            model = ClaudeCLIProvider(
                settings.qve_claude_model, settings.qve_claude_executable, settings.qve_cli_timeout
            )
        elif selected == "antigravity_cli":
            model = AntigravityCLIProvider(
                settings.qve_antigravity_model,
                settings.qve_antigravity_executable,
                settings.qve_cli_timeout,
                settings.qve_antigravity_effort,
            )
        elif selected == "gemini_cli":
            model = GeminiCLIProvider(
                settings.qve_gemini_model, settings.qve_gemini_executable, settings.qve_cli_timeout
            )
        else:
            model = CodexCLIProvider()
        model.check()
        return model
    if selected != "openai":
        raise ValueError(
            "Configure QVE_AI_PROVIDER=openai or inject another AIProvider implementation"
        )
    return OpenAIProvider(
        settings.openai_api_key,
        settings.qve_ai_model,
        settings.qve_ai_model_version,
        settings.qve_ai_reasoning,
        settings.qve_ai_temperature,
    )


# Preserve the public factory imported by existing preparation scripts.
provider = build_provider


def serialize(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def latest(db, as_of, quarter=None):
    query = select(AIAnalystSnapshot).join(AIAnalysisRun)
    if quarter:
        query = query.where(AIAnalysisRun.quarter == quarter)
    return db.scalar(
        query.where(
            AIAnalystSnapshot.company_id == 1, AIAnalystSnapshot.as_of_timestamp <= at_time(as_of)
        ).order_by(AIAnalystSnapshot.as_of_timestamp.desc(), AIAnalystSnapshot.id.desc())
    )


def register(app):
    @app.command("ai-provider-check")
    def ai_provider_check(provider: str = "claude_cli"):
        model = build_provider(Settings(), name=provider)
        emit(
            model.probe()
            if isinstance(model, (GeminiCLIProvider, AntigravityCLIProvider))
            else model.check()
        )

    @app.command("ai-run-validation-set")
    def ai_run_validation_set(
        ticker: str = "NVDA", provider: str = "claude_cli", repeat: bool = False
    ):
        from valuation_engine.ai.validation import run_validation

        require_ticker(ticker)
        emit(run_validation(Settings(), repeat=repeat, provider=provider))

    @app.command("ai-compare-providers")
    def ai_compare_providers(
        ticker: str = "NVDA",
        quarter: str = "FY2027-Q2",
        provider_a: str = "claude_cli",
        provider_b: str = "antigravity_cli",
    ):
        from valuation_engine.ai.validation import compare_providers

        require_ticker(ticker)
        with Session(engine(Settings().qve_database_url)) as db:
            emit(compare_providers(db, quarter, provider_a, provider_b))

    @app.command("ai-review-status")
    def ai_review_status(ticker: str = "NVDA", provider: str = "claude_cli"):
        from valuation_engine.ai.validation import review_status

        require_ticker(ticker)
        with Session(engine(Settings().qve_database_url)) as db:
            emit(review_status(db, provider))

    @app.command("ai-analyze")
    def ai_analyze(
        ticker: str = "NVDA",
        quarter: str = "FY2027-Q2",
        prepare_only: bool = False,
        recorded: str | None = None,
        refresh: bool = False,
        json_output: bool = False,
        provider: str = "claude_cli",
    ):
        require_ticker(ticker)
        settings = Settings()
        with Session(engine(settings.qve_database_url)) as db:
            quant = resolve_run(db, 1, quarter)
            if prepare_only:
                emit(prepare(db, quant, settings.qve_raw_dir))
                return
            selected_model = build_provider(settings, recorded, provider)
            if (
                isinstance(selected_model, (GeminiCLIProvider, AntigravityCLIProvider))
                and not selected_model.probe()["ready"]
            ):
                emit({"status": "unavailable", "reason": "Official subscription CLI probe failed"})
                return
            snapshot = analyze(
                db,
                quant,
                selected_model,
                settings.qve_raw_dir,
                refresh,
            )
            db.commit()
            if snapshot is None:
                emit(
                    {
                        "status": "unavailable",
                        "reason": "See append-only ai_analysis_events; no fabricated snapshot",
                    }
                )
            elif json_output:
                emit(serialize(snapshot))
            else:
                import typer

                typer.echo(f"NVDA {quarter} | AI Analyst | {snapshot.model_version}")
                for name, value in snapshot.metadata_json["features"].items():
                    typer.echo(
                        f"{name}: {value['feature_value']:+.2f} | Confidence {value['confidence']:.0%} | {value['net_assessment']}"
                    )
                typer.echo("Missing: " + ", ".join(snapshot.metadata_json["missing_features"]))
                for challenge in snapshot.metadata_json["challenges"]:
                    typer.echo(f"{challenge['kind']}: {challenge['description']}")
                typer.echo(
                    "Evidence-linked research hypotheses; human semantic review status must be checked separately."
                )

    @app.command("ai-history")
    def ai_history(ticker: str = "NVDA"):
        require_ticker(ticker)
        with Session(engine(Settings().qve_database_url)) as db:
            emit(
                [
                    serialize(r)
                    for r in db.scalars(
                        select(AIAnalysisRun)
                        .where(AIAnalysisRun.company_id == 1)
                        .order_by(AIAnalysisRun.as_of_timestamp, AIAnalysisRun.id)
                    )
                ]
            )

    @app.command("ai-features")
    def ai_features(ticker: str = "NVDA", as_of: str | None = None, quarter: str | None = None):
        require_ticker(ticker)
        with Session(engine(Settings().qve_database_url)) as db:
            s = latest(db, as_of, quarter)
            emit(
                {"status": "unavailable"}
                if s is None
                else {
                    "snapshot": serialize(s),
                    "features": [
                        serialize(r)
                        for r in db.scalars(
                            select(AIAnalystFeature).where(
                                AIAnalystFeature.analysis_run_id == s.analysis_run_id
                            )
                        )
                    ],
                }
            )

    @app.command("ai-challenges")
    def ai_challenges(ticker: str = "NVDA", as_of: str | None = None, quarter: str | None = None):
        require_ticker(ticker)
        with Session(engine(Settings().qve_database_url)) as db:
            s = latest(db, as_of, quarter)
            emit(
                {"status": "unavailable"}
                if s is None
                else [
                    serialize(r)
                    for r in db.scalars(
                        select(AIChallenge).where(AIChallenge.analysis_run_id == s.analysis_run_id)
                    )
                ]
            )

    @app.command("ai-evidence")
    def ai_evidence(analysis_run: int):
        with Session(engine(Settings().qve_database_url)) as db:
            emit(
                [
                    serialize(r)
                    for r in db.scalars(
                        select(AIEvidence).where(AIEvidence.analysis_run_id == analysis_run)
                    )
                ]
            )

    @app.command("ai-export-recording")
    def ai_export_recording(analysis_run: int, out: Path):
        from valuation_engine.db.schema import AIProviderCall

        with Session(engine(Settings().qve_database_url)) as db:
            run = db.get(AIAnalysisRun, analysis_run)
            completed = db.scalar(
                select(AIAnalystSnapshot).where(AIAnalystSnapshot.analysis_run_id == analysis_run)
            )
            if run is None or completed is None:
                raise ValueError("Only completed analyses can be exported for replay")
            calls = {
                c.request_hash: c.raw_output
                for c in db.scalars(
                    select(AIProviderCall)
                    .where(
                        AIProviderCall.analysis_run_id == analysis_run,
                        AIProviderCall.status == "valid",
                    )
                    .order_by(AIProviderCall.id)
                )
            }
            out.write_text(
                json.dumps(
                    {
                        "provider": run.model_provider,
                        "model_name": run.model_name,
                        "model_version": run.model_version,
                        "settings": run.settings_json,
                        "calls": calls,
                    },
                    indent=2,
                )
                + "\n"
            )
            emit({"recording": str(out), "calls": len(calls)})

    @app.command("ai-review-import")
    def ai_review_import(path: Path):
        from valuation_engine.ai.validation import HumanReviewSubmission

        reviews = [HumanReviewSubmission.model_validate(x) for x in json.loads(path.read_text())]
        with Session(engine(Settings().qve_database_url)) as db:
            for review in reviews:
                if (
                    db.scalar(
                        select(AIAnalystSnapshot).where(
                            AIAnalystSnapshot.analysis_run_id == review.analysis_run_id
                        )
                    )
                    is None
                ):
                    raise ValueError("Human review requires an actual completed analysis")
                ids = set(
                    db.scalars(
                        select(AIEvidence.id).where(
                            AIEvidence.analysis_run_id == review.analysis_run_id
                        )
                    )
                )
                if not set(review.evidence_ids) <= ids:
                    raise ValueError("Review evidence must belong to the same run")
                if not review.evidence_ids:
                    raise ValueError("Human review requires evidence references")
                db.add(
                    AIHumanReview(
                        **review.model_dump(exclude={"reviewed_at"}), created_at=review.reviewed_at
                    )
                )
            db.commit()
            emit({"human_reviews_appended": len(reviews)})

    @app.command("research-view")
    def research_view(ticker: str = "NVDA", as_of: str | None = None):
        require_ticker(ticker)
        with Session(engine(Settings().qve_database_url)) as db:
            quant = resolve_run(db, 1, cutoff=at_time(as_of))
            ctx = context_for(db, quant)
            valuation = db.scalar(
                select(ResearchValuation).where(
                    ResearchValuation.forecast_run_id == quant.id,
                    ResearchValuation.as_of_timestamp <= quant.forecast_as_of,
                )
            )
            snap = db.scalar(
                select(AIAnalystSnapshot)
                .join(AIAnalysisRun)
                .where(
                    AIAnalysisRun.company_id == 1,
                    AIAnalysisRun.quarter == ctx["quarter"],
                    AIAnalysisRun.as_of_timestamp == quant.forecast_as_of,
                )
                .order_by(AIAnalystSnapshot.id.desc())
            )
            emit(
                {
                    "quant": ctx["quant_forecasts"],
                    "regime": ctx["regime"],
                    "valuation": {
                        k: getattr(valuation, k)
                        for k in (
                            "ntm_pe",
                            "forward_fcf_yield",
                            "dcf_base",
                            "reverse_dcf_implied_fcf_cagr",
                        )
                    }
                    if valuation
                    else None,
                    "ai": serialize(snap) if snap else {"status": "unavailable"},
                    "read_only": True,
                }
            )
