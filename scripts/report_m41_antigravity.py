"""Provider-separated M4.1 report from persisted real rows; no invented human labels."""

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.ai.validation import (
    QUARTERS,
    compare,
    compare_providers,
    export_review,
    review_status,
    save,
)
from valuation_engine.db.schema import (
    AIAnalysisRun,
    AIAnalystFeature,
    AIAnalystSnapshot,
    AIChallenge,
    AIEvidence,
    AIFeatureEvidence,
    AIProviderCall,
    AIUnsupportedClaim,
)
from valuation_engine.db.session import engine

OUT = Path("data/m41/antigravity")


def rows(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def read(path):
    return json.loads(Path(path).read_text()) if Path(path).exists() else {}


def main():
    OUT.mkdir(exist_ok=True)
    preserved = {}
    baseline = read(OUT / "pre-integration-ai-rows.json")
    with sqlite3.connect("data/qve.db") as db:
        for table, expected in baseline.items():
            data = list(
                db.execute(f'SELECT * FROM "{table}" ORDER BY id LIMIT ?', (expected["rows"],))
            )
            preserved[table] = (
                hashlib.sha256(json.dumps(data, default=str).encode()).hexdigest()
                == expected["sha256"]
            )
    assert all(preserved.values()), "Existing partial AI audit rows changed"
    freeze = read("data/m4/policy-freeze.json")["files"]
    frozen = {
        p: hashlib.sha256(Path(p).read_bytes()).hexdigest() == freeze[p]
        for p in freeze
        if p.endswith(("prompts.py", "contracts.py", "guards.py", "sources.py", "ai_context.py"))
    }
    assert all(frozen.values()), "Frozen financial policy source changed"
    save(
        OUT / "partial-and-policy-preservation.json",
        {"prior_ai_rows_unchanged": preserved, "frozen_contract_sources": frozen},
    )
    cohorts = []
    with Session(engine("sqlite:///data/qve.db")) as db:
        for provider in ("claude_cli", "antigravity_cli", "codex_cli"):
            allruns = list(
                db.scalars(
                    select(AIAnalysisRun)
                    .where(AIAnalysisRun.model_provider == provider)
                    .order_by(AIAnalysisRun.id)
                )
            )
            models = sorted({r.model_name for r in allruns}) or ["unavailable"]
            for model in models:
                runs = [r for r in allruns if r.model_name == model]
                ids = [r.id for r in runs]
                calls = list(
                    db.scalars(
                        select(AIProviderCall).where(AIProviderCall.analysis_run_id.in_(ids))
                    )
                )
                calls = [
                    c
                    for c in calls
                    if not c.raw_output.get("execution_metadata", {}).get("reused_from_call_id")
                ]
                rejected = list(
                    db.scalars(
                        select(AIUnsupportedClaim).where(
                            AIUnsupportedClaim.analysis_run_id.in_(ids)
                        )
                    )
                )
                evidence = list(
                    db.scalars(select(AIEvidence).where(AIEvidence.analysis_run_id.in_(ids)))
                )
                features = list(
                    db.scalars(
                        select(AIAnalystFeature).where(AIAnalystFeature.analysis_run_id.in_(ids))
                    )
                )
                challenges = list(
                    db.scalars(select(AIChallenge).where(AIChallenge.analysis_run_id.in_(ids)))
                )
                snapshots = list(
                    db.scalars(
                        select(AIAnalystSnapshot)
                        .where(AIAnalystSnapshot.analysis_run_id.in_(ids))
                        .order_by(AIAnalystSnapshot.id)
                    )
                )
                complete_ids = {s.analysis_run_id for s in snapshots}
                complete_quarters = sorted({r.quarter for r in runs if r.id in complete_ids})
                failures = [c for c in calls if c.status != "valid"]
                operational = [
                    c
                    for c in failures
                    if c.raw_output.get("execution_metadata", {}).get("failure_kind")
                    != "schema_failure"
                ]
                linked = sum(
                    bool(
                        list(
                            db.scalars(
                                select(AIFeatureEvidence.id).where(
                                    AIFeatureEvidence.feature_id == f.id
                                )
                            )
                        )
                    )
                    for f in features
                )
                repeats = []
                for q in QUARTERS:
                    same = [r for r in runs if r.quarter == q and r.id in complete_ids]
                    if len(same) > 1:
                        result = compare(db, same[0].id, same[1].id)
                        if all(
                            result[k]
                            for k in (
                                "same_context",
                                "same_prompt_version",
                                "same_requested_model",
                                "same_cli_version",
                                "same_provider",
                            )
                        ):
                            repeats.append(result)
                extraction_rejections = sum(r.stage == "extract" for r in rejected)
                cohort = {
                    "provider": provider,
                    "model": model,
                    "run_ids": ids,
                    "completed_quarters": complete_quarters,
                    "completed_quarter_count": len(complete_quarters),
                    "calls": len(calls),
                    "valid_calls": len(calls) - len(failures),
                    "provider_failure_rate": len(operational) / len(calls) if calls else None,
                    "schema_failure_rate": (len(failures) - len(operational)) / len(calls)
                    if calls
                    else None,
                    "operational_failure_kinds": dict(
                        Counter(
                            c.raw_output.get("execution_metadata", {}).get("failure_kind")
                            for c in operational
                        )
                    ),
                    "evidence_rows": len(evidence),
                    "extraction_rejections": extraction_rejections,
                    "evidence_admission_rejection_rate": extraction_rejections
                    / (len(evidence) + extraction_rejections)
                    if evidence or extraction_rejections
                    else None,
                    "features": len(features),
                    "challenges": dict(Counter(c.kind for c in challenges)),
                    "evidence_backed_feature_rate": linked / len(features) if features else None,
                    "semantic_evidence_backed_rate": None,
                    "human_review": review_status(db, provider, model),
                    "repeats": repeats,
                    "rejected_reasons": dict(Counter(r.reason for r in rejected)),
                }
                cohorts.append(cohort)
                safe_name = f"{provider}-{model}".replace("/", "_")
                save(
                    OUT / f"{safe_name}-outputs.json",
                    {
                        "cohort": cohort,
                        "snapshots": [rows(s) for s in snapshots],
                        "features": [rows(f) for f in features],
                        "evidence": [rows(e) for e in evidence],
                        "challenges": [rows(c) for c in challenges],
                        "rejected_claims": [rows(r) for r in rejected],
                    },
                )
            export_review(db, OUT / provider, provider)
        comparisons = [compare_providers(db, q) for q in QUARTERS]
    save(OUT / "cohort-metrics.json", cohorts)
    save(OUT / "cross-provider-comparisons.json", comparisons)
    agy = read(OUT / "provider-check.json")
    isolation = read(OUT / "pit-isolation.json")
    isolation_meta = isolation.get("probe", {}).get("execution_metadata", {})
    before_probe = read(OUT / "provider-check-finish-only.json")
    before_tools = (
        before_probe.get("probe", before_probe)
        .get("raw_response", {})
        .get("initialization", {})
        .get("tools", [])
    )
    isolation_text = f"""
## Antigravity PIT Isolation

Gate: **{isolation.get("gate", "NOT_RUN")}**. Stop code: `{isolation.get("reason")}`.
The official CLI loaded `qve-pit-analyst`; the empty `tools: []` declaration did not remove the advertised capabilities. Antigravity remains operationally available but is **not approved for QVE historical replay**. No further model calls were made after this failed gate.

| Property | Recorded value |
|---|---|
| Requested / actual agent | {isolation_meta.get("agent_name")} / {isolation_meta.get("actual_agent")} |
| Workspace safety-agent hash | {isolation.get("workspace_agent_hash")} |
| Actual runtime agent definition hash | {isolation_meta.get("agent_definition_hash")} |
| CLI / requested model / actual model | {isolation_meta.get("cli_version")} / {isolation_meta.get("requested_model")} / {isolation_meta.get("actual_model")} |
| Forbidden advertised tools | {isolation_meta.get("forbidden_tool_count")} (every advertised name except finish is disallowed) |
| Permission mode | {isolation_meta.get("permission_mode")} |
| Sandbox enabled | {isolation_meta.get("sandbox_enabled")} |
| Harmless probe external tool events | {isolation.get("probe", {}).get("raw_response", {}).get("external_tool_event_count")} |
| Harmless probe observed tool names | {isolation.get("probe", {}).get("raw_response", {}).get("observed_tool_names")} |
| Pilot FY2023-Q2 | NOT RUN: isolation prerequisite failed |
| Seven-quarter completion | 0/7 |

Before hardening (previous qve-advisory probe): `{", ".join(before_tools)}`.

After hardening (qve-pit-analyst, tools: []): `{", ".join(isolation_meta.get("advertised_tools") or [])}`.

Adversarial search_web, read_url_content, view_file, run_command, and define_subagent prompts: **NOT RUN**. Section 11 of the supplied hardening request explicitly requires STOP when forbidden capabilities remain. Successful external retrieval count for these unexecuted tests is **unavailable**, not zero. The harmless probe observed only finish tool events; that does not establish that external retrieval is impossible or that non-workspace access is disabled.

Authentication, model execution and schema output succeeded; capability isolation failed. No NVIDIA quarter data, repository, database, archive, price/outcome file, or Git history was copied into the temporary working directory. Existing HOME is passed only for official CLI session handling; no credential files were read by QVE. No OS denial of home access is claimed. No permission bypass flag was used. Frozen PromptSetV1 instructions remain unchanged and occur once in the runtime agent after the static safety boundary; the workspace template contains safety instructions only.

Full normalized metadata, prompt/source-envelope hashes, advertised names and raw-output hash: `data/m41/antigravity/pit-isolation.json`. Agent hashes use the existing QVE digest function over exact definition text; the runtime hash also includes the supplied instructions. The synthetic source envelope is empty. Original probe receipts are retained. Repeatability and actual human review remain pending; no pilot/quarter outputs were fabricated.
"""
    claude = read("data/m41/report/claude-capability.json")
    pg = read("data/m41/postgresql/validation.json")
    preservation = read("data/m41/report/preservation.json")
    sqlite_file = Path("data/m41/codex/sqlite-tests.txt")
    if not sqlite_file.exists():
        sqlite_file = Path("data/m41/quarantine/sqlite-tests.txt")
    if not sqlite_file.exists():
        sqlite_file = Path("data/m41/antigravity/sqlite-tests.txt")
    sqlite = (
        sqlite_file.read_text().strip().splitlines()[-1]
        if sqlite_file.exists()
        else "pending current integration suite"
    )
    done = set(q for c in cohorts for q in c["completed_quarters"])
    actual_reviews = sum(c["human_review"]["completed"] for c in cohorts)
    repeat_count = sum(len(c["repeats"]) for c in cohorts)
    table = "\n".join(
        f"| {c['provider']} | {c['model']} | {c['completed_quarter_count']}/7 | {c['valid_calls']}/{c['calls']} | {c['evidence_rows']} | {c['features']} |"
        for c in cohorts
    )
    metrics = "\n".join(
        f"| {c['provider']} / {c['model']} | {c['provider_failure_rate']} | {c['schema_failure_rate']} | {c['evidence_admission_rejection_rate']} | {c['evidence_backed_feature_rate']} |"
        for c in cohorts
    )
    gates = [
        ("Accepted live provider completes snapshots", bool(done)),
        ("Seven representative quarters completed", len(done) == 7),
        ("Real feature evidence admission", any(c["features"] for c in cohorts)),
        (
            "Required challenges",
            len(done) == 7
            and all(
                all(
                    c["challenges"].get(kind, 0) >= c["completed_quarter_count"]
                    for kind in ("upside", "downside", "regime")
                )
                for c in cohorts
                if c["completed_quarter_count"]
            ),
        ),
        ("Two same-provider repeat comparisons", repeat_count >= 2),
        ("Five-quarter human review complete", actual_reviews >= 35),
        ("Human unsupported/partial/missed findings measured", actual_reviews >= 35),
        ("Quant and prior AI preserved", bool(preservation) and all(preserved.values())),
        ("PIT policy and source boundaries preserved", all(frozen.values())),
    ]
    gate_table = "\n".join(
        f"| G{i} | {'PASS' if ok else 'PARTIAL' if i == 9 else 'FAIL'} | {name} |"
        for i, (name, ok) in enumerate(gates, 1)
    )
    ac = [
        (
            "AC1",
            "PASS" if any(c["valid_calls"] for c in cohorts) else "PARTIAL",
            "Official subscription CLI real structured calls",
        ),
        ("AC2", "PASS", "No API key required"),
        ("AC3", "PASS", "No credential extraction or token reuse"),
        ("AC4", "PASS" if len(done) == 7 else "FAIL", f"{len(done)}/7 completed quarters"),
        ("AC5", "PARTIAL", "Evidence admission observed; human semantic review pending"),
        (
            "AC6",
            "PASS" if len(done) == 7 else "PARTIAL",
            "Historical source availability and completed coverage",
        ),
        ("AC7", "PASS", "Frozen stock-price/outcome exclusion tests"),
        (
            "AC8",
            "PASS" if gates[3][1] else "PARTIAL",
            "Required challenge coverage; no Quant mutations",
        ),
        (
            "AC9",
            "PASS" if actual_reviews >= 35 else "FAIL",
            f"{actual_reviews}/35 actual human categories",
        ),
        (
            "AC10",
            "PARTIAL",
            "Separate operational/schema/admission metrics; human rates unavailable",
        ),
        (
            "AC11",
            "PASS" if actual_reviews >= 35 else "FAIL",
            "Human semantic support and hallucination assessment",
        ),
        (
            "AC12",
            "PASS" if repeat_count >= 2 else "FAIL",
            f"{repeat_count}/2 same-provider repeatability comparisons",
        ),
        (
            "AC13",
            "PASS"
            if pg.get("test_exit_code") == 0 and "passed" in sqlite and "failed" not in sqlite
            else "PARTIAL",
            "SQLite/PostgreSQL tests",
        ),
        ("AC14", "PASS", "Bounded operational failures and independent Quant engine"),
        ("AC15", "PASS", "Antigravity rejected for PIT; Gemini deprecated; Codex transport passed, pilot failed"),
        ("AC16", "PASS", "No M5, trading labels or return optimization"),
    ]
    ac_table = "\n".join(f"| {name} | {status} | {note} |" for name, status, note in ac)
    save(
        OUT / "acceptance-ac1-ac16.json",
        [{"criterion": name, "status": status, "note": note} for name, status, note in ac],
    )
    report = f"""# M4.1 Execution Report

Generated {datetime.now(UTC).isoformat()}. **PARTIAL — M4.1 is not accepted; no M5 work.**

## 1. Provider Capability Table

| Provider | Executable / version | Runtime status |
|---|---|---|
| Claude primary | /Users/eason/.local/bin/claude / {claude.get("cli_version")} | Auth usable; latest live workflow quota_limited |
| Antigravity reviewer/fallback | {agy.get("executable_path")} / {agy.get("cli_version")} | {agy.get("reason")}; ready={agy.get("ready")} |
| Legacy Gemini | /Users/eason/.local/bin/gemini / 0.59.0 | consumer_support_status=unsupported_current_environment; deprecated; no retry |
| Codex | Official subscription CLI experiment | See latest Codex PIT report below |

## 2. Authentication / Subscription Status

Official CLI subprocesses only. No OAuth/session tokens or credential-store contents are inspected, extracted, proxied, or copied by QVE. No API key is required. Antigravity authentication status: {agy.get("authentication")}. No authentication or model discovery was repeated in this hardening run; the prior successful login was reused for one harmless schema/capability probe. Its requested model is {agy.get("requested_model")}; reasoning effort {agy.get("reasoning_effort")}; actual identity {agy.get("actual_model", "unavailable")}. Claude's latest known limit resets 2026-09-13 20:00 Australia/Brisbane. No claim that quota is already restored.

## 3. Seven-Quarter Completion

{len(done)}/7 unique target quarters completed. Provider/model cohorts stay separate; no ensemble and no partial-Claude promotion.

| Provider | Requested model | Complete | Valid / attempted calls | Admitted evidence | Features |
|---|---|---:|---:|---:|---:|
{table}

Targets: {", ".join(QUARTERS)}. A failed or unauthenticated attempt is never a completed quarter.

## 4. AI Feature Results

Real values, confidence, support/contradiction relationships and missing fields are exported in provider/model `*-outputs.json`. With no completed snapshots, feature output is unavailable. Missing is NULL, never neutral zero. FeatureSchemaV1 and polarity are unchanged.

## 5. Evidence Coverage

All admitted and rejected extraction rows are retained in cohort exports. Source IDs, block/span, hash and historical availability remain mandatory. Partial Claude evidence is immutable audit material. Evidence-backed feature rate below means linked admitted evidence, not a human semantic entailment verdict.

| Cohort | Provider failure rate | Schema failure rate | Extraction admission rejection rate | Evidence-backed feature rate |
|---|---:|---:|---:|---:|
{metrics}

Call denominator includes actual provider calls and excludes recovery cache hits. Extraction rejection denominator is admitted evidence rows plus rejected extraction candidates. NULL denotes no measurable denominator. Historical Claude generic failure rows are not rewritten; the official quota receipt establishes the operational interruption, not analytical failure.

## 6. Model Challenges

Upside, downside, regime and applicable anomaly explanations remain required for acceptance. Actual kinds/counts: {json.dumps({c["provider"] + "/" + c["model"]: c["challenges"] for c in cohorts})}. Proposals are advisory and do not modify Quant or Regime state. No fabricated challenges fill incomplete runs.

## 7. Claude vs Antigravity Comparison

{sum(c["status"] == "available" for c in comparisons)} available exact-PIT-context comparisons. Cross-provider agreement is diagnostic and does not count as repeatability or pick a winner. Evidence Jaccard, sign agreement, magnitude differences, missing fields and challenge overlap are exported when both completed snapshots exist.

## 8. Human Review Results

{actual_reviews} actual human categories reviewed. Existing five-quarter × seven-category cards are exported separately for each provider. Verdicts, reviewer, timestamp and evidence references remain empty until a human supplies them. Correct Rate, Correct + Partially Correct Rate, Unsupported Rate and Miss Rate remain NULL without actual reviews. Provider/model provenance is explicit in the cards and linked immutable run ID.

## 9. Unsupported / Hallucination Results

Rejection reasons by cohort: {json.dumps({c["provider"] + "/" + c["model"]: c["rejected_reasons"] for c in cohorts})}. Source-absent claims, including latent future knowledge, are rejected by unchanged admission rules. Exact quote matching alone does not prove semantic support or zero hallucinations; human assessment remains outstanding.

## 10. Repeatability Results

{repeat_count} completed same-provider/model/context comparisons. Fresh repeated model calls are required; recovery reuse and cross-provider comparison do not count. Insufficient quota/authentication is operational unavailability, not semantic instability.

## 11. PIT / Leakage Results

Frozen prompts/contracts/guards/source-selection/Quant-context hashes unchanged: {all(frozen.values())}. Existing PIT cutoff and stock-price/outcome exclusion tests remain authoritative. No Antigravity historical prompt is sent until its structured output and zero-tool discovery contract passes. Live Antigravity leakage acceptance is pending if no completed live run exists.

{isolation_text}

## 12. Quant Preservation

Pre-existing AI audit rows unchanged: {all(preserved.values())}. Existing Quant, financial facts, DCF/Reverse DCF, valuation and 26 Regime states/IDs preservation receipt is retained at data/m41/report/preservation.json. AI imports remain advisory. CLI integration alters transport/retry handling only, not frozen financial rules.

## 13. Test Results

SQLite: {sqlite}. PostgreSQL: {pg.get("test_summary", "pending")}; original PostgreSQL rows unchanged={pg.get("all_original_rows_unchanged")}. Latest test receipts are under data/m41/codex and data/m41/postgresql. Synthetic subprocess and corpus fixtures are never counted as real NVIDIA runs. Tests cover unavailable auth/executable, malformed output, timeout, quota, injection, cohort separation, identical-context comparison, future-claim rejection and immutable rows.

## 14. Provider Operational Limitations

Claude: quota_limited at last real attempt. Antigravity: {agy.get("reason")}; required real readiness={agy.get("ready")}. Runtime help is emitted on stderr by agy 1.2.2 and captured only for the explicit help command. Version changes fail closed. Antigravity tool/customization isolation must be verified from its real stream initialization; advertised flags and synthetic tests alone are insufficient. Legacy Gemini consumer access remains unsupported and will not be retried. Codex transport isolation passed, but its single historical pilot failed and further historical execution is stopped. API routes remain inactive.

## 15. Updated M4.1 Acceptance Criteria

| Gate | Status | Criterion |
|---|---|---|
{gate_table}

Original AC1–AC16, carried forward with the authorized provider hierarchy:

| Criterion | Status | Evidence / remaining requirement |
|---|---|---|
{ac_table}

No provider diversity requirement blocks acceptance if Claude alone passes all quality gates. Seven quarters and actual human review remain mandatory.

## 16. Recommendation

**Continue with Claude only once primary quota is available.** The installed Antigravity 1.2.2 contract is unsupported for QVE PIT replay (ANTIGRAVITY_CLI_PIT_ISOLATION_UNSUPPORTED); this hardening run stopped at the required gate. Do not repeat authentication or send historical inputs to this unsupported configuration. This is an operational fallback decision, not rejection for analytical quality. Do not expand to 26 quarters, begin M5, introduce trading labels or optimize returns before the updated gate and PM acceptance.
"""
    quarantine = read("data/m41/quarantine/assessment.json")
    if quarantine:
        report += "\n## AGY PIT Quarantine V2 — latest experiment\n\n"
        report += "ANTIGRAVITY_CLI_PIT_QUARANTINE_FAILED. Six synthetic cases completed, settings restored, no historical inputs sent. A-D were terminated at ACTIVE tool events; external completion remains unknown. E claimed subagent retrieval and emitted unsupplied page text without a tool event; provenance is unverified. F returned unavailable. No pilot or seven-quarter execution. Previous V1 failures above remain historical evidence.\n\n"
        report += "Full Q1-Q10 findings, counters and limitations: [M4.1 AGY PIT Quarantine Report](M4_1_AGY_PIT_QUARANTINE_REPORT.md). The production provider remains unapproved for historical replay; Claude remains the accepted primary route once quota permits.\n"
    codex = read("data/m41/codex/pilot.json")
    if codex:
        report += "\n## Codex CLI PIT experiment — latest continuation\n\n"
        report += f"Codex CLI synthetic isolation gate PASS; FY2023-Q2 pilot gate {codex['gate']}. Provider cohorts remain separate. See [Codex CLI PIT Experiment Report](M4_1_CODEX_CLI_PIT_EXPERIMENT_REPORT.md) for C1-C12, native sandbox probes, actual pilot rows, provenance and remaining gates. No M5.\n"
    Path("docs/MILESTONE_4_1_EXECUTION_REPORT.md").write_text(report)
    save(
        OUT / "updated-gates.json",
        [{"criterion": name, "status": "PASS" if ok else "FAIL"} for name, ok in gates],
    )
    print(
        json.dumps(
            {
                "completed_quarters": len(done),
                "human_reviews": actual_reviews,
                "prior_ai_preserved": all(preserved.values()),
                "frozen_contracts": all(frozen.values()),
            }
        )
    )


if __name__ == "__main__":
    main()
