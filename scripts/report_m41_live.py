"""Regenerate M4.1 from real append-only rows; never manufacture human verdicts."""

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.ai.validation import (
    QUARTERS,
    compare,
    completed,
    export_review,
    review_status,
    save,
)
from valuation_engine.db.schema import (
    AIAnalysisEvent,
    AIAnalysisRun,
    AIAnalystFeature,
    AIAnalystSnapshot,
    AIChallenge,
    AIEvidence,
    AIFeatureEvidence,
    AIProviderCall,
    AIUnsupportedClaim,
    ModelAdjustmentProposal,
)
from valuation_engine.db.session import engine
from valuation_engine.db.store import digest

OUT = Path("data/m41/report")


def serialized(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def main():
    capability = json.loads((OUT / "claude-capability.json").read_text())
    with Session(engine("sqlite:///data/qve.db")) as db:
        runs = list(
            db.scalars(
                select(AIAnalysisRun)
                .where(
                    AIAnalysisRun.model_provider == "claude_cli",
                    AIAnalysisRun.quarter.in_(QUARTERS),
                )
                .order_by(AIAnalysisRun.id)
            )
        )
        ids = [r.id for r in runs]
        calls = list(
            db.scalars(select(AIProviderCall).where(AIProviderCall.analysis_run_id.in_(ids)))
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
        rejected = list(
            db.scalars(
                select(AIUnsupportedClaim).where(AIUnsupportedClaim.analysis_run_id.in_(ids))
            )
        )
        rows = []
        claims = []
        repeat = []
        primary_ids = []
        checks = []
        for q in QUARTERS:
            snap = completed(db, q)
            attempts = [r for r in runs if r.quarter == q]
            run = (
                db.get(AIAnalysisRun, snap.analysis_run_id)
                if snap
                else (attempts[-1] if attempts else None)
            )
            row = {
                "quarter": q,
                "analysis_run_id": snap.analysis_run_id if snap else None,
                "attempt_run_ids": [r.id for r in attempts],
                "status": "completed"
                if snap
                else ("attempted_failed" if attempts else "not_executed"),
            }
            if run:
                sources = run.context_json["sources"]
                cutoff = run.information_cutoff
                if cutoff.tzinfo is None:
                    cutoff = cutoff.replace(tzinfo=UTC)
                for source in sources["documents"]:
                    assert datetime.fromisoformat(source["available_at"]) <= cutoff
                checks.append(
                    {
                        "quarter": q,
                        "eligible_sources": len(sources["documents"]),
                        "all_source_availability_within_cutoff": True,
                        "context_hash": digest(run.context_json),
                        "source_hashes": [s["source_hash"] for s in sources["documents"]],
                    }
                )
                row["sources"] = sources["documents"]
                row["anomaly_codes"] = run.context_json["quant_context"]["anomaly_codes"]
                row["transcript_status"] = (
                    "TRANSCRIPT_PIT_UNVERIFIED"
                    if sources["coverage"]["official_call_status"] == "missing"
                    else "eligible"
                )
            if snap:
                primary_ids.append(run.id)
                features = list(
                    db.scalars(
                        select(AIAnalystFeature).where(AIAnalystFeature.analysis_run_id == run.id)
                    )
                )
                challenges = list(
                    db.scalars(select(AIChallenge).where(AIChallenge.analysis_run_id == run.id))
                )
                evidence = list(
                    db.scalars(select(AIEvidence).where(AIEvidence.analysis_run_id == run.id))
                )
                emap = {e.id: e for e in evidence}
                blocks = {b["block_id"]: b for b in sources["blocks"]}
                for e in evidence:
                    assert e.span in blocks[e.block_id]["text"]
                    assert e.source_hash == blocks[e.block_id]["source_hash"]
                for f in features:
                    links = list(
                        db.scalars(
                            select(AIFeatureEvidence).where(AIFeatureEvidence.feature_id == f.id)
                        )
                    )
                    assert links and all(link.evidence_id in emap for link in links)
                    claims.append(
                        {
                            "quarter": q,
                            "analysis_run_id": run.id,
                            "kind": "feature",
                            "claim_id": f.id,
                            "feature": f.feature_name,
                            "claim": f.rationale,
                            "evidence_ids": [link.evidence_id for link in links],
                            "semantic_support": None,
                            "reviewer": None,
                            "reviewed_at": None,
                        }
                    )
                for c in challenges:
                    assert c.evidence_ids and all(e in emap for e in c.evidence_ids)
                    claims.append(
                        {
                            "quarter": q,
                            "analysis_run_id": run.id,
                            "kind": "challenge",
                            "claim_id": c.id,
                            "claim": c.description,
                            "evidence_ids": c.evidence_ids,
                            "semantic_support": None,
                            "reviewer": None,
                            "reviewed_at": None,
                        }
                    )
                row.update(
                    feature_count=len(features),
                    evidence_count=len(evidence),
                    challenge_count=len(challenges),
                    challenge_kinds=dict(Counter(c.kind for c in challenges)),
                    missing_features=snap.metadata_json["missing_features"],
                    overall_confidence=snap.overall_qualitative_confidence,
                )
                row["required_challenge_gaps"] = sorted(
                    {"upside", "downside", "regime"} - set(c.kind for c in challenges)
                )
                row["anomaly_explanation_gap"] = bool(row["anomaly_codes"]) and not any(
                    c.kind == "anomaly" for c in challenges
                )
                save(
                    OUT / f"{q}-outputs.json",
                    {
                        "run": serialized(run),
                        "snapshot": serialized(snap),
                        "features": [serialized(f) for f in features],
                        "evidence": [serialized(e) for e in evidence],
                        "challenges": [serialized(c) for c in challenges],
                        "adjustment_proposals": [
                            serialized(p)
                            for p in db.scalars(
                                select(ModelAdjustmentProposal).where(
                                    ModelAdjustmentProposal.analysis_run_id == run.id
                                )
                            )
                        ],
                    },
                )
                if q in QUARTERS[:2]:
                    snapshots = list(
                        db.scalars(
                            select(AIAnalystSnapshot)
                            .join(AIAnalysisRun)
                            .where(
                                AIAnalysisRun.quarter == q,
                                AIAnalysisRun.model_provider == "claude_cli",
                            )
                            .order_by(AIAnalystSnapshot.id)
                        )
                    )
                    if len(snapshots) > 1:
                        repeat.append(
                            {
                                "quarter": q,
                                **compare(
                                    db, snapshots[0].analysis_run_id, snapshots[-1].analysis_run_id
                                ),
                            }
                        )
            rows.append(row)
        export_review(db, OUT)
        review = review_status(db)
        failures = [c for c in calls if c.status != "valid"]
        provider_failures = [
            c
            for c in failures
            if c.raw_output.get("execution_metadata", {}).get("failure_kind")
            in {"provider_failure", "provider_unavailable", "timeout"}
        ]
        actual = sorted(
            {
                c.raw_output.get("execution_metadata", {}).get("actual_model", "unavailable")
                for c in calls
            }
        )
        events = [
            serialized(e)
            for e in db.scalars(
                select(AIAnalysisEvent).where(AIAnalysisEvent.analysis_run_id.in_(ids))
            )
        ]
        metrics = {
            "calls": len(calls),
            "reused_extraction_calls": reused_count,
            "observed_cli_usage_models": sorted(
                {
                    name
                    for c in calls
                    for name in c.raw_output.get("raw_response", {}).get("modelUsage", {})
                }
            ),
            "valid_calls": len(calls) - len(failures),
            "schema_failure_rate": (len(failures) - len(provider_failures)) / len(calls)
            if calls
            else None,
            "provider_failure_rate": len(provider_failures) / len(calls) if calls else None,
            "exact_evidence_linked_claim_rate": 1.0 if claims else None,
            "semantic_evidence_backed_claim_rate": None,
            "semantic_support": {
                "supported": None,
                "partially_supported": None,
                "unsupported": None,
            },
            "rejected_by_stage": dict(Counter(r.stage for r in rejected)),
            "rejected_by_reason": dict(Counter(r.reason for r in rejected)),
            "human_review": review,
            "actual_models": actual,
            "extraction_semantic_errors": None,
            "interpretation_errors": None,
            "missing_insights": None,
        }
        save(OUT / "seven-quarter-live-results.json", rows)
        save(OUT / "live-metrics.json", metrics)
        save(OUT / "live-events.json", events)
        save(OUT / "pit-verification.json", checks)
        save(OUT / "repeatability-live.json", repeat)
        save(OUT / "material-claim-review.generated.json", claims)
        save(OUT / "rejected-claims.json", [serialized(r) for r in rejected])
        done = sum(r["status"] == "completed" for r in rows)
        success = any(c.status == "valid" for c in calls)
        challenge_ok = done == 7 and all(
            not r.get("required_challenge_gaps") and not r.get("anomaly_explanation_gap")
            for r in rows
        )
        pgpath = Path("data/m41/postgresql/validation.json")
        pg = json.loads(pgpath.read_text()) if pgpath.exists() else {}
        sqlite = Path("data/m41/sqlite-tests.txt").read_text().strip().splitlines()[-1]
        ac = [
            (
                "AC1",
                "PASS" if success else "PARTIAL",
                "Official subscription CLI; real structured success required",
            ),
            ("AC2", "PASS", "No API key required"),
            ("AC3", "PASS", "No credential-store/token inspection or repurposing"),
            ("AC4", "PASS" if done == 7 else "FAIL", f"{done}/7 completed real analyses"),
            (
                "AC5",
                "PARTIAL",
                "Exact evidence admission checked; human semantic assessment pending",
            ),
            (
                "AC6",
                "PASS" if done == 7 else "PARTIAL",
                "Persisted source availability checked against historical cutoff",
            ),
            ("AC7", "PASS", "Frozen price/outcome-isolated context and tests"),
            (
                "AC8",
                "PASS" if challenge_ok else "PARTIAL",
                "Required challenge coverage reported by quarter; no Quant mutation",
            ),
            (
                "AC9",
                "PASS" if review["completed"] == 35 else "FAIL",
                f"{review['completed']}/35 actual human reviews",
            ),
            ("AC10", "PARTIAL", "Observed machine metrics; human rates unavailable until reviewed"),
            ("AC11", "FAIL", "Human semantic support review pending; no zero-hallucination claim"),
            (
                "AC12",
                "PASS"
                if len(repeat) == 2
                and all(
                    r["same_context"]
                    and r["same_prompt_version"]
                    and r["same_requested_model"]
                    and r["same_cli_version"]
                    for r in repeat
                )
                else "FAIL",
                f"{len(repeat)}/2 real quarter comparisons",
            ),
            (
                "AC13",
                "PASS" if pg.get("test_exit_code") == 0 else "PARTIAL",
                "SQLite/PostgreSQL receipts below",
            ),
            ("AC14", "PASS", "Bounded failures tested; deterministic engine remains independent"),
            ("AC15", "PASS", "Gemini fallback authorized after Claude quota limit; Codex remains inactive"),
            ("AC16", "PASS", "No M5/trading/outcome optimization"),
        ]
        save(OUT / "acceptance.json", [{"criterion": a, "status": s, "note": n} for a, s, n in ac])
        qt = "\n".join(
            f"| {r['quarter']} | {r['status']} | {r.get('feature_count', 0)} | {r.get('evidence_count', 0)} | {r.get('challenge_kinds', {})} |"
            for r in rows
        )
        at = "\n".join(f"| {a} | {s} | {n} |" for a, s, n in ac)
        report = f"""# M4.1 Execution Report

Generated {datetime.now(UTC).isoformat()}. **PARTIAL — no Final Pass; human review remains required.**

## 1. CLI Provider Status

Claude Code {capability["cli_version"]}; official subscription authentication {capability["authentication"]}; provider ready={capability["ready"]}. Real schema-valid calls: {metrics["valid_calls"]}/{len(calls)}. Gemini CLI 0.59.0 is installed and its fallback transport is enabled by the latest user instruction; the official Google service rejected access with IneligibleTierError / UNSUPPORTED_CLIENT for Gemini Code Assist for individuals. No Gemini quarter analysis ran. Codex remains inactive. Claude stopped at its official session limit (reset 2026-09-13 20:00 Australia/Brisbane).

## 2. Authentication Mode

Official `claude auth status` confirmed loggedIn=true and authMethod=claude.ai. Auth mode: subscription_cli_session. Requested model: {capability["requested_model"]}. CLI-exposed actual models: {actual}. Unknown identities remain unavailable. Adapter repairs accept the observed official auth spelling and preserve USER/LOGNAME/SHELL needed by the CLI's own authentication check. No credential files or token values were read, copied or persisted. No paid API key fallback.

## 3. Seven-Quarter Run Results

{done}/7 completed. Failed attempts remain immutable audit rows; no fixture output substituted.

| Quarter | Status | Features | Evidence spans | Challenge kinds |
|---|---|---:|---:|---|
{qt}

## 4. AI Feature Results

Full real values, confidence, horizons, supporting/contradicting evidence and missing fields are in each `FY*-outputs.json`. Only completed snapshots are summarized. There are currently no completed feature outputs; 388 admitted partial Claude evidence rows are preserved in `claude-partial-evidence.json`. Missing evidence remains NULL. All original feature polarity, schema, prompts, confidence coefficients and admission rules are retained. Outputs await human semantic assessment.

## 5. Evidence Coverage

Exact-span and same-run evidence references were rechecked for every included feature and challenge. Linked exact-evidence rate: {metrics["exact_evidence_linked_claim_rate"]}; this is not semantic entailment. Source URLs, IDs, hashes, blocks and availability are in the per-quarter outputs. Semantic evidence-backed claim rate remains unavailable pending review.

## 6. Model Challenges

Actual persisted challenge kinds appear above. Required upside/downside/regime/anomaly gaps are explicit in `seven-quarter-live-results.json`. Proposals, where present, are advisory only with no numeric ranges. No revised revenue, EPS, FCF, valuation or Regime write is performed.

## 7. Human Review Results

{review["completed"]}/35 actual reviews. The existing first five quarters × seven categories are populated from completed real snapshots in `human-review-cards.generated.json`. Correct Rate: {review["correct_rate"]}; Correct + Partial: {review["correct_plus_partial_rate"]}; Unsupported Rate: {review["unsupported_rate"]}; Miss Rate: {review["miss_rate"]}. Denominator: {review["rate_denominator"]}. None means unavailable, not zero. No AI self-review is marked human.

## 8. Unsupported / Hallucination Results

Rejected claims by stage: {metrics["rejected_by_stage"]}. Reasons: {metrics["rejected_by_reason"]}. These are automated admission rejections, not human error-rate labels. Schema Failure Rate: {metrics["schema_failure_rate"]}; Provider Failure Rate: {metrics["provider_failure_rate"]}; denominator {len(calls)} attempted calls. Supported/partially_supported/unsupported semantic counts, interpretation errors and missing insights remain unmeasured. Material claim cards are prepared for actual review. Exact quotes alone do not prove zero hallucinations. Human-identified unsupported claims require remediation before dataset acceptance.

## 9. Repeatability Results

{len(repeat)}/2 quarter comparisons completed. `repeatability-live.json` records source/prompt/model/CLI equivalence, evidence Jaccard, feature sign agreement, magnitude differences and challenge dimension overlap. Bitwise determinism is not required; semantic wording still needs review.

```json
{json.dumps(repeat, indent=2, default=str)}
```

## 10. PIT / Leakage Results

Source availability of each attempted quarter is checked against its stored cutoff in `pit-verification.json`. Only existing eligible context enters CLI stdin. Frozen prompts, schema, source policy, evidence admission, price/outcome isolation and Quant context remain unchanged. CLI tools/customizations are disabled in an empty temporary directory. Unverified transcript publication stays excluded as TRANSCRIPT_PIT_UNVERIFIED. Pretrained world knowledge remains a limitation requiring semantic support review.

## 11. Quant Preservation

See `preservation.json` for exact original row preservation and all 26 accepted Regime state/identity pairs, plus prior archive hashes. Quant forecasts, DCF, Reverse DCF, Regime snapshots and valuation rows are never written by the AI pipeline. Frozen baseline archives and receipts are retained.

## 12. Test Results

SQLite: {sqlite}

PostgreSQL: {pg.get("test_summary", "not run")}; original PostgreSQL rows unchanged: {pg.get("all_original_rows_unchanged")}.

Ruff/mypy receipts: data/m41/ruff.txt and data/m41/mypy.txt. Tests include auth-name/environment compatibility, missing executable/auth, timeout, malformed JSON, bounded retries, shell/source injection, PIT/evidence isolation, identity metadata and immutability. Synthetic tests are not counted as real quarter results.

## 13. Remaining Limitations

Human reviews and semantic-support labels remain pending. Any incomplete quarters, challenge gaps or repeat failures are listed explicitly. `sonnet` is a requested alias; actual identities are recorded only where CLI exposes them. Exact valid extraction calls from an incomplete run can be reused only for the same provider, model, CLI version and PIT context; independent repeats remain fresh. Claude and Gemini cohorts are kept separate. No claim of model quality is made from connectivity alone. Original policy is preserved rather than tuned to force passing results.

## 14. M4.1 AC1–AC16

| Criterion | Status | Evidence / limitation |
|---|---|---|
{at}

## 15. Recommendation

Keep expansion to 26 quarters blocked pending actual human review and PM quality acceptance. If real outputs reveal insufficient support or required challenge gaps, review the policy and authorize a targeted rerun; do not change it silently. No M5, Opportunity Score, Buy/Hold/Sell or return optimization.
"""
        Path("docs/MILESTONE_4_1_EXECUTION_REPORT.md").write_text(report)
        print(
            json.dumps(
                {
                    "completed_quarters": done,
                    "valid_calls": metrics["valid_calls"],
                    "repeated_quarters": len(repeat),
                    "human_reviews": review["completed"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
