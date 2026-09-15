"""Evidence-driven M4.1 status. Missing live/human measurements remain unavailable."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from valuation_engine.ai.validation import save

ROOT = Path("data/m41")
OUT = ROOT / "report"


def main():
    capability = json.loads((OUT / "claude-capability.json").read_text())
    results = json.loads((OUT / "seven-quarter-results.json").read_text())
    reviews = json.loads((OUT / "human-review-status.json").read_text())
    optional = json.loads((OUT / "optional-capabilities.json").read_text())
    pg = ROOT / "postgresql/validation.json"
    pg_result = json.loads(pg.read_text()) if pg.exists() else None
    sqlite = (ROOT / "sqlite-tests.txt").read_text().strip().splitlines()[-1]
    completed = sum(r["status"] == "completed" for r in results)
    original = json.loads(Path("data/m4/policy-freeze.json").read_text())
    changes = [
        p
        for p, h in original["files"].items()
        if hashlib.sha256(Path(p).read_bytes()).hexdigest() != h
    ]
    assert changes == ["src/valuation_engine/ai/service.py"]
    save(
        ROOT / "transport-freeze.json",
        {
            "created_at": datetime.now(UTC).isoformat(),
            "transport": "CLITransportV1",
            "requested_model": capability["requested_model"],
            "cli_version": capability["cli_version"],
            "prior_m4_manifest_sha256": hashlib.sha256(
                Path("data/m4/policy-freeze.json").read_bytes()
            ).hexdigest(),
            "changed_prior_files": changes,
            "reason": "CLI identity metadata, seven-quarter execution gate; no policy/schema/source/admission changes",
            "files": {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(Path("src/valuation_engine/ai").glob("*.py"))
            },
        },
    )
    table = "\n".join(
        f"| {r['quarter']} | {r['status']} | {r['source_coverage']['narrative_blocks']} |"
        for r in results
    )
    statuses = [
        (
            "AC1",
            "PARTIAL",
            "Official adapter tested synthetically; authenticated live execution unavailable",
        ),
        ("AC2", "PASS", "Primary workflow requires no API key"),
        ("AC3", "PASS", "Only official executable; no credential-store/token access"),
        ("AC4", "FAIL", f"{completed}/7 real quarters completed"),
        ("AC5", "PARTIAL", "Evidence admission tests pass; no live features to evaluate"),
        ("AC6", "PARTIAL", "Seven PIT contexts prepared; live seven-quarter execution pending"),
        ("AC7", "PASS", "Existing price/outcome isolation tests pass; context pipeline unchanged"),
        ("AC8", "PARTIAL", "Quant preserved; no real model challenges yet"),
        ("AC9", "FAIL", f"{reviews['completed']}/35 actual human reviews"),
        ("AC10", "PARTIAL", "Metrics tooling exists; no human denominator, rates NULL"),
        ("AC11", "FAIL", "No actual semantic-support review"),
        ("AC12", "FAIL", "Repeat runner/comparison implemented; real repeats not executed"),
        (
            "AC13",
            "PASS" if pg_result and pg_result["test_exit_code"] == 0 else "PARTIAL",
            "SQLite tested; "
            + (pg_result["test_summary"] if pg_result else "current PostgreSQL check pending"),
        ),
        ("AC14", "PASS", "Provider failures and bounded retries tested; Quant remains independent"),
        ("AC15", "PASS", "Optional adapters only; no Gemini/Codex model calls"),
        ("AC16", "PASS", "No M5, Opportunity Score, Buy/Sell or return optimization"),
    ]
    ac = "\n".join(f"| {a} | {s} | {n} |" for a, s, n in statuses)
    capabilities = "\n".join(
        f"| {c['provider_type']} | {c['executable']} | {c['cli_version']} | {c['authentication']} | {c['ready']} |"
        for c in [capability, *optional]
    )
    report = f"""# M4.1 Execution Report

Status: **PARTIAL — subscription login and real validation pending; no Final Pass.**
Generated: {datetime.now(UTC).isoformat()}

## 1. CLI Provider Status

| Provider | Executable | Version | Authentication | Ready |
|---|---|---|---|---|
{capabilities}

Claude supports the required installed flags. No live call is represented by synthetic tests.

## 2. Authentication Mode

`subscription_cli_session`. Official `claude auth status --json` returned loggedIn=false,
authMethod=none, including outside the restricted sandbox. User must complete `claude auth login`.
No token, keychain value or credential file was read/extracted. Requested model is explicitly
`{capability["requested_model"]}`; actual model unavailable. No API key is required.

## 3. Seven-Quarter Run Results

| Quarter | Real analysis status | Eligible narrative blocks |
|---|---|---|
{table}

No expansion to 26. Preparation is not model execution.

## 4. AI Feature Results

Real feature snapshots: {completed}. No fabricated feature values; missing remains NULL.
Frozen feature polarity and admission schema are unchanged.

## 5. Evidence Coverage

Seven contexts contain eligible official releases and SEC filings. Full source IDs, hashes,
availability and block references are in the quarter context files. Exact evidence-backed
claim rate is unavailable until real results exist; semantic support additionally needs review.

## 6. Model Challenges

No real upside/downside/regime/anomaly challenges yet. Existing evidence mapping, advisory-only
proposals and numeric-write prohibitions remain unchanged.

## 7. Human Review Results

{reviews["completed"]}/35 completed. Existing five-quarter/seven-category set preserved in
`human-review-cards.generated.json`. These are preparation cards while outputs are unavailable.
The importer requires a reviewer, timezone-aware review time, notes and same-run evidence.
Correct Rate, Correct + Partial, Unsupported Rate and Miss Rate: unavailable (denominator zero).
No AI self-review is labelled human review.

## 8. Unsupported / Hallucination Results

Supported, partially_supported, unsupported: unavailable. Extraction rejections are separately
counted by stage; interpretation errors and missing insights need human judgment. Schema/provider
failure rates for live calls are unavailable. Synthetic failures are not mixed into NVIDIA quality
metrics. Exact quotes do not establish zero hallucinations. No live output has been admitted.

## 9. Repeatability Results

Not executed. `ai-run-validation-set --repeat` reruns FY2023-Q2 and FY2023-Q3 and records source,
prompt, requested-model and CLI-version equivalence, evidence overlap, feature direction/magnitude
and challenge dimension overlap. This does not assert human semantic equivalence.

## 10. PIT / Leakage Results

Original PIT/source/price/outcome code unchanged. Transcript gaps are explicitly
`TRANSCRIPT_PIT_UNVERIFIED`; publication-time requirements were not relaxed. CLI tools and
customizations are disabled, with an empty temporary working directory. Pretrained world knowledge
remains a limitation requiring evidence admission and human semantic evaluation.

## 11. Quant Preservation

Pre-M4.1 SQLite backups were created. Preservation receipt checks original rows, all 26 M3.1
state/identity pairs and prior M2/M3/M3.1/M4 archives. The original M4 freeze is untouched.
Only service.py changed among frozen M4 files (transport identity metadata and seven-quarter gate).
`transport-freeze.json` records the separate CLI transport implementation. No database migration.

## 12. Test Results

SQLite: {sqlite}

PostgreSQL: {pg_result["test_summary"] if pg_result else "Current M4.1 run pending; prior M4 result is not substituted."}

Tests cover process/stdin boundaries, missing executable/auth, timeout cleanup, malformed output,
nonzero exit, API-key exclusion, unsupported flags, version drift, optional-provider no-run gate,
bounded retry and metadata, historical evidence/isolation/immutability, and human timestamp parsing.
Ruff and mypy results are recorded separately. No real Claude success is claimed from mocks.

## 13. Remaining Limitations

Claude login is missing; real seven-quarter output, real repeatability and human review remain
uncompleted. Gemini executable was not found; Codex auth was not tested and it was not activated.
The requested model is an alias until a full identifier is configured. A quarter interrupted before
commit requires rerun; the CLI may perform internal retries within the enforced process timeout.
Review import trusts the submitter's human attestation; it is not an identity-verification service.
Human-found unsupported claims require reviewed remediation before an accepted dataset is released.

## 14. M4.1 AC1–AC16

| Criterion | Status | Evidence / limitation |
|---|---|---|
{ac}

## 15. Recommendation

Keep the seven-quarter validation gate closed. Complete official Claude subscription login, execute
the seven quarters and two repeats, then obtain actual human review. There is no evidence yet to
recommend expansion, policy revision based on quality, or abandoning the provider for poor quality.
Do not begin M5. M4 Final Pass remains withheld.
"""
    Path("docs/MILESTONE_4_1_EXECUTION_REPORT.md").write_text(report)
    save(OUT / "acceptance.json", [dict(criterion=a, status=s, note=n) for a, s, n in statuses])
    print("M4.1 report generated; real execution and human gate remain pending.")


if __name__ == "__main__":
    main()
