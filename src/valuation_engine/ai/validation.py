"""Seven-quarter execution gate and evidence-linked human review preparation."""

import json
from collections import Counter
from pathlib import Path

from pydantic import AwareDatetime
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from valuation_engine.ai.antigravity_provider import AntigravityCLIProvider
from valuation_engine.ai.cli_provider import ClaudeCLIProvider, GeminiCLIProvider
from valuation_engine.ai.contracts import ReviewDraft
from valuation_engine.ai.recovery import recovery_provider
from valuation_engine.ai.service import analyze, prepare
from valuation_engine.db.schema import (
    AIAnalysisRun,
    AIAnalystFeature,
    AIAnalystSnapshot,
    AIChallenge,
    AIEvidence,
    AIHumanReview,
    AIProviderCall,
    AIUnsupportedClaim,
)
from valuation_engine.db.session import engine
from valuation_engine.db.store import digest
from valuation_engine.quant.ai_context import resolve_run
from valuation_engine.research.numbers import canonical

QUARTERS = (
    "FY2023-Q2",
    "FY2023-Q3",
    "FY2024-Q1",
    "FY2024-Q2",
    "FY2025-Q4",
    "FY2026-Q1",
    "FY2027-Q2",
)
CATEGORIES = (
    "demand",
    "supply",
    "competition",
    "product_cycle",
    "management",
    "anomalies",
    "model_challenge",
)


class HumanReviewSubmission(ReviewDraft):
    """Review timestamp supplied by the human, distinct from model execution."""

    reviewed_at: AwareDatetime


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(canonical(value), indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def completed(db, quarter, provider="claude_cli", model=None):
    return db.scalar(
        select(AIAnalystSnapshot)
        .join(AIAnalysisRun)
        .where(
            AIAnalysisRun.company_id == 1,
            AIAnalysisRun.quarter == quarter,
            AIAnalysisRun.model_provider == provider,
            AIAnalysisRun.model_name == model if model is not None else true(),
        )
        .order_by(AIAnalystSnapshot.id.asc())
    )


def review_status(db, provider="claude_cli", model=None):
    selected = {q: completed(db, q, provider, model) for q in QUARTERS[:5]}
    reviews = []
    pending = []
    for quarter, snapshot in selected.items():
        for category in CATEGORIES:
            row = (
                None
                if snapshot is None
                else db.scalar(
                    select(AIHumanReview)
                    .where(
                        AIHumanReview.analysis_run_id == snapshot.analysis_run_id,
                        AIHumanReview.category == category,
                    )
                    .order_by(AIHumanReview.id.desc())
                )
            )
            if row is not None:
                reviews.append(row)
            else:
                pending.append({"quarter": quarter, "category": category})
    counts = Counter(r.verdict for r in reviews)
    n = len(reviews)
    return {
        "required": 35,
        "completed": n,
        "pending": pending,
        "correct_rate": counts["correct"] / n if n else None,
        "correct_plus_partial_rate": (counts["correct"] + counts["partially_correct"]) / n
        if n
        else None,
        "unsupported_rate": counts["unsupported"] / n if n else None,
        "miss_rate": counts["missed"] / n if n else None,
        "rate_denominator": n,
        "human_gate_complete": n == 35,
        "expansion_requires_pm_approval": True,
    }


def export_review(db, out, provider="claude_cli", model=None):
    cards = []
    for quarter in QUARTERS[:5]:
        snap = completed(db, quarter, provider, model)
        run_id = snap.analysis_run_id if snap else None
        evidence = (
            []
            if snap is None
            else [
                {
                    "id": e.id,
                    "source_document_id": e.source_document_id,
                    "source_hash": e.source_hash,
                    "block_id": e.block_id,
                    "span": e.span,
                    "topic": e.topic,
                    "section": e.section,
                }
                for e in db.scalars(select(AIEvidence).where(AIEvidence.analysis_run_id == run_id))
            ]
        )
        for category in CATEGORIES:
            cards.append(
                {
                    "quarter": quarter,
                    "provider": provider,
                    "model": db.get(AIAnalysisRun, run_id).model_name if run_id else None,
                    "prompt_version": db.get(AIAnalysisRun, run_id).prompt_version
                    if run_id
                    else None,
                    "analysis_run_id": run_id,
                    "category": category,
                    "verdict": None,
                    "reviewer": None,
                    "reviewed_at": None,
                    "notes": None,
                    "evidence_ids": [],
                    "evidence": evidence,
                    "ai_snapshot": snap.metadata_json if snap else None,
                    "semantic_support": None,
                    "instructions": "Actual human only. Assess material claims as supported/partially_supported/unsupported; classify extraction, interpretation, unsupported, and missed insight errors. Import ReviewDraft fields plus reviewed_at (timezone required); created_at preserves the human-supplied review time. Record semantic assessment in notes.",
                }
            )
    # Generated cards never overwrite filled reviews.
    save(out / "human-review-cards.generated.json", cards)
    save(out / "human-review-status.json", review_status(db, provider, model))


def compare(db, first, second):
    a, b = db.get(AIAnalysisRun, first), db.get(AIAnalysisRun, second)

    def spans(run):
        return set(
            db.scalars(select(AIEvidence.span_hash).where(AIEvidence.analysis_run_id == run))
        )

    def features(run):
        return {
            f.feature_name: f.feature_value
            for f in db.scalars(
                select(AIAnalystFeature).where(AIAnalystFeature.analysis_run_id == run)
            )
        }

    def challenges(run):
        return {
            (c.kind, c.direction, c.target_variable)
            for c in db.scalars(select(AIChallenge).where(AIChallenge.analysis_run_id == run))
        }

    x, y = spans(first), spans(second)
    af, bf = features(first), features(second)
    common = af.keys() & bf.keys()
    ac, bc = challenges(first), challenges(second)
    return {
        "first_run": first,
        "second_run": second,
        "same_provider": a.model_provider == b.model_provider,
        "same_context": digest(a.context_json) == digest(b.context_json),
        "same_prompt_version": a.prompt_version == b.prompt_version,
        "same_requested_model": a.model_name == b.model_name,
        "same_cli_version": a.settings_json["cli_version"] == b.settings_json["cli_version"],
        "evidence_jaccard": len(x & y) / len(x | y) if x | y else None,
        "feature_direction_agreement": sum(
            (af[k] > 0) == (bf[k] > 0) and (af[k] < 0) == (bf[k] < 0) for k in common
        )
        / len(common)
        if common
        else None,
        "mean_absolute_magnitude_difference": sum(abs(af[k] - bf[k]) for k in common) / len(common)
        if common
        else None,
        "common_feature_count": len(common),
        "missing_in_either": sorted(af.keys() ^ bf.keys()),
        "missing_from_first": sorted(bf.keys() - af.keys()),
        "missing_from_second": sorted(af.keys() - bf.keys()),
        "opposite_sign_features": sorted(k for k in common if af[k] * bf[k] < 0),
        "challenge_dimension_jaccard": len(ac & bc) / len(ac | bc) if ac | bc else None,
        "semantic_stability": "human_interpretation_required",
    }


def run_validation(
    settings, repeat=False, execute=True, out=Path("data/m41/report"), provider="claude_cli"
):
    model: ClaudeCLIProvider | GeminiCLIProvider | AntigravityCLIProvider = ClaudeCLIProvider(
        settings.qve_claude_model, settings.qve_claude_executable, settings.qve_cli_timeout
    )
    if provider == "antigravity_cli":
        model = AntigravityCLIProvider(
            settings.qve_antigravity_model,
            settings.qve_antigravity_executable,
            settings.qve_cli_timeout,
            settings.qve_antigravity_effort,
        )
        out = out / "antigravity"
    elif provider == "gemini_cli":
        model = GeminiCLIProvider(
            settings.qve_gemini_model, settings.qve_gemini_executable, settings.qve_cli_timeout
        )
        out = out / "gemini"
    elif provider != "claude_cli":
        raise ValueError("Only approved CLI providers may execute M4.1")
    capability = (
        model.probe()
        if isinstance(model, (GeminiCLIProvider, AntigravityCLIProvider))
        else model.check()
    )
    save(out / f"{provider}-capability.json", capability)
    results, repeats = [], []
    halted = None
    with Session(engine(settings.qve_database_url)) as db:
        for quarter in QUARTERS:
            quant = resolve_run(db, 1, quarter)
            context = prepare(db, quant, settings.qve_raw_dir)
            save(out / f"{quarter}-context.json", context)
            snap = completed(db, quarter, provider, model.model_name)
            if execute and capability["ready"] and snap is None and not halted:
                resumed = recovery_provider(db, model, context)
                snap = analyze(db, quant, resumed, settings.qve_raw_dir)
                db.commit()
                last = db.scalar(
                    select(AIProviderCall)
                    .join(AIAnalysisRun)
                    .where(
                        AIAnalysisRun.model_provider == provider, AIAnalysisRun.quarter == quarter
                    )
                    .order_by(AIProviderCall.id.desc())
                )
                failure = (
                    last.raw_output.get("execution_metadata", {}).get("failure_kind")
                    if last
                    else None
                )
                if failure in {
                    "quota_limited",
                    "authentication_failure",
                    "unsupported_client",
                    "isolation_contract_failure",
                    "ANTIGRAVITY_CLI_PIT_ISOLATION_UNSUPPORTED",
                }:
                    halted = failure
            row = {
                "quarter": quarter,
                "provider": provider,
                "provider_execution_status": halted
                or (
                    capability.get("reason")
                    if not capability["ready"]
                    else ("completed" if snap else "not_completed")
                ),
                "context_hash": digest(context),
                "source_coverage": context["sources"]["coverage"],
                "transcript_exclusion": "TRANSCRIPT_PIT_UNVERIFIED"
                if context["sources"]["coverage"]["official_call_status"] == "missing"
                else None,
                "analysis_run_id": snap.analysis_run_id if snap else None,
                "status": "completed"
                if snap
                else ("provider_unavailable" if not capability["ready"] else "not_completed"),
                "human_semantic_review": "pending",
            }
            results.append(row)
            save(out / "seven-quarter-results.json", results)
        if repeat and execute and capability["ready"] and not halted:
            for quarter in QUARTERS[:2]:
                original = completed(db, quarter, provider, model.model_name)
                if original is None:
                    continue
                original_run = db.get(AIAnalysisRun, original.analysis_run_id)
                if original_run is None:
                    raise ValueError("Completed snapshot has no analysis run")
                repeat_quant = resolve_run(db, 1, quarter)
                if (
                    digest(original_run.context_json)
                    != digest(prepare(db, repeat_quant, settings.qve_raw_dir))
                    or original_run.model_name != model.model_name
                    or original_run.settings_json.get("cli_version")
                    != model.settings["cli_version"]
                ):
                    repeats.append({"quarter": quarter, "status": "repeat_configuration_mismatch"})
                    continue
                repeated = analyze(db, repeat_quant, model, settings.qve_raw_dir, refresh=True)
                db.commit()
                if repeated:
                    repeats.append(compare(db, original.analysis_run_id, repeated.analysis_run_id))
                else:
                    repeats.append({"quarter": quarter, "status": "repeat_failed"})
            save(out / "repeatability.json", repeats)
        export_review(db, out, provider, model.model_name)
        ids = list(
            db.scalars(
                select(AIAnalysisRun.id).where(
                    AIAnalysisRun.company_id == 1,
                    AIAnalysisRun.model_provider == provider,
                    AIAnalysisRun.quarter.in_(QUARTERS),
                )
            )
        )
        calls = list(
            db.scalars(select(AIProviderCall).where(AIProviderCall.analysis_run_id.in_(ids)))
        )
        rejected = list(
            db.scalars(
                select(AIUnsupportedClaim).where(AIUnsupportedClaim.analysis_run_id.in_(ids))
            )
        )
        reused_count = sum(
            bool(c.raw_output.get("execution_metadata", {}).get("reused_from_call_id"))
            for c in calls
        )
        calls = [
            c
            for c in calls
            if not c.raw_output.get("execution_metadata", {}).get("reused_from_call_id")
        ]
        failed = [c for c in calls if c.status != "valid"]
        provider_failures = [
            c
            for c in failed
            if c.raw_output.get("execution_metadata", {}).get("failure_kind")
            in {
                "provider_failure",
                "provider_unavailable",
                "timeout",
                "quota_limited",
                "authentication_failure",
                "unsupported_client",
                "isolation_contract_failure",
                "ANTIGRAVITY_CLI_PIT_ISOLATION_UNSUPPORTED",
            }
        ]
        save(
            out / "automated-metrics.json",
            {
                "all_attempted_run_calls": len(calls),
                "provider": provider,
                "operational_failures_by_kind": dict(
                    Counter(
                        c.raw_output.get("execution_metadata", {}).get("failure_kind")
                        for c in provider_failures
                    )
                ),
                "reused_extraction_calls": reused_count,
                "invalid_calls": sum(c.status != "valid" for c in calls),
                "schema_failure_rate": (len(failed) - len(provider_failures)) / len(calls)
                if calls
                else None,
                "provider_failure_rate": len(provider_failures) / len(calls) if calls else None,
                "evidence_backed_claim_rate": None,
                "rate_denominator_calls": len(calls),
                "interpretation_errors": None,
                "missing_insights": None,
                "rejected_by_stage": dict(Counter(r.stage for r in rejected)),
                "semantic_support": {
                    "supported": None,
                    "partially_supported": None,
                    "unsupported": None,
                },
                "note": "Quote validation is not semantic support; pending actual human assessment.",
            },
        )
    return {
        "provider": capability,
        "quarters": results,
        "repeats": repeats,
        "review_cards": str(out / "human-review-cards.generated.json"),
    }


def compare_providers(db, quarter, provider_a="claude_cli", provider_b="antigravity_cli"):
    """Compare completed snapshots at one exact PIT context; never merge or choose a winner."""
    if provider_a == provider_b:
        raise ValueError("Cross-provider diagnostic requires distinct providers")

    def runs(provider):
        return list(
            db.scalars(
                select(AIAnalysisRun)
                .join(AIAnalystSnapshot)
                .where(
                    AIAnalysisRun.company_id == 1,
                    AIAnalysisRun.quarter == quarter,
                    AIAnalysisRun.model_provider == provider,
                )
                .order_by(AIAnalysisRun.id)
            )
        )

    a, b = runs(provider_a), runs(provider_b)
    for first in a:
        for second in b:
            if (
                digest(first.context_json),
                first.prompt_version,
                first.schema_version,
                first.policy_version,
            ) != (
                digest(second.context_json),
                second.prompt_version,
                second.schema_version,
                second.policy_version,
            ):
                continue
            return {
                **compare(db, first.id, second.id),
                "status": "available",
                "comparison_type": "cross_provider_diagnostic",
                "quarter": quarter,
                "provider_a": provider_a,
                "provider_b": provider_b,
                "model_a": first.model_name,
                "model_b": second.model_name,
                "automatic_winner": None,
                "ensemble": False,
                "counts_as_repeatability": False,
            }
    return {
        "status": "unavailable",
        "reason": "NO_COMPLETED_MATCHING_PIT_CONTEXT",
        "quarter": quarter,
        "provider_a": provider_a,
        "provider_b": provider_b,
        "counts_as_repeatability": False,
    }
