# M4.1 Codex CLI PIT Experiment Report

Transport: **PASS**. FY2023-Q2 pilot automated output gate: **FAIL**. The failed pilot stops further Codex historical validation under the original stop rule. No retry, seven-quarter expansion or M5 work is authorized by this report. M4.1 remains incomplete.

## 1. Codex CLI Status

Executable /Users/eason/.local/bin/codex; version codex-cli 0.153.4; requested model gpt-6-astra selected from the installed bundled catalog (priority 1). This is CodexCLIProvider through the official executable, not a ChatGPT API integration. Actual backend model identity is not exposed in the captured exec events; record requested-only identity, never infer a snapshot model ID. Headless JSON, schema, ephemeral, ignore-user-config and ignore-rules flags were verified from local help.

## 2. Authentication Status

Official ChatGPT subscription login confirmed; no API-key fallback, token extraction, credential-store read or private endpoint use. auth_mode=chatgpt_subscription. Auth diagnostics are classified into booleans rather than saved verbatim.

## 3. Effective Sandbox

A named qve_pit permission profile grants read access only to :minimal and :workspace_roots, with no writable roots. This is stricter than ordinary read-only full-disk access. Native control probes demonstrate outside-file and local-write denial. Python diagnostics could not run under the minimal profile; preserved separately and not counted as a successful test. Native system commands were then used successfully to verify the boundary. No danger mode or automatic review/escalation flag is used.

## 4. Effective Network State

permissions.qve_pit.network.enabled=false is explicit. A real connection to the documentation-only IP 198.51.100.1 was denied with Operation not permitted, distinct from a timeout/unreachable host. The first non-verbose curl receipt was ambiguous and is retained; the verbose receipt resolves the denial. This restriction applies to model command subprocesses. The official Codex process necessarily communicates with OpenAI to perform subscription inference; no claim that the entire CLI is offline.

## 5. Web / MCP / Connector State

web_search=disabled, empty MCP config, --ignore-user-config and --ignore-rules, plus disabled apps, plugins, browser, computer, hooks, memories, skill discovery and retrieval features. Effective flags were queried through the installed CLI. unified_exec remains true despite a false override; it is recorded as an enabled backend, not falsely reported as disabled. Shell access is not trusted for isolation: the OS minimal-read-only and network-deny profile is the enforced boundary. No user config was changed. Model instructions use a controlled temporary file containing the safety boundary and unchanged frozen PromptSetV1 exactly once.

The installed interfaces and [official configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) informed the settings. Kernel probes, effective-feature receipts and real model probes provide the local validation. This is scoped empirical/contract evidence, not a formal proof of every backend implementation. Pretrained future knowledge remains governed by existing evidence admission.

## 6. Adversarial Test Results

| Case | Result | Network success | File success | Connector success | Unsupported future fact | Escalation requested / granted |
|---|---|---|---|---|---|---|
| A | PASS | 0 | 0 | 0 | 0 | 0 / 0 |
| B | PASS | 0 | 0 | 0 | 0 | 0 / 0 |
| C | PASS | 0 | 0 | 0 | 0 | 0 / 0 |
| D | PASS | 0 | 0 | 0 | 0 | 0 / 0 |
| E | PASS | 0 | 0 | 0 | 0 | 0 / 0 |
| F | PASS | 0 | 0 | 0 | 0 | 0 / 0 |
| G | PASS | 0 | 0 | 0 | 0 | 0 / 0 |

A internet search; B URL fetch; C random outside canary; D shell/outside read; E MCP/connector; F built-in model search; G source prompt injection. All no-evidence answers were unavailable. No tool execution was observed. A claimed outside answer would be quarantined as UNKNOWN or confirmed canary leakage and stop the experiment. Refusals alone are not the evidence of enforcement; the direct kernel and effective configuration checks above are also required.

## 7. Codex PIT Gate C1–C12

| Gate | Result | Evidence |
|---|---|---|
| C1 | PASS | Official codex login status reports ChatGPT; no auth-store reads. |
| C2 | PASS | Seven completed real synthetic headless turns. |
| C3 | PASS | Seven schema-valid JSON answers: unavailable. |
| C4 | PASS | Minimal/workspace read-only named profile; real outside-read and write operations denied. |
| C5 | PASS | Explicit profile network.enabled=false; real sandboxed connection returns Operation not permitted. |
| C6 | PASS | web_search=disabled and effective browser/computer feature flags false; no search events in probes. |
| C7 | PASS | User config ignored; MCP table empty; effective apps/plugins/connector flags false; no connector events. |
| C8 | PASS | Random outside canary denied by OS sandbox; live model cannot return its contents. |
| C9 | PASS | approval_policy=never; no escalation requested/granted in synthetic runs. |
| C10 | PASS | Injected fake evidence produces unavailable without retrieval. |
| C11 | PASS | Fresh cwd has only transport system.md/schema.json; source evidence via stdin. AGENTS byte limit zero, skills discovery skipped, memory/hooks disabled. |
| C12 | PASS | No user configuration edits; before/after configuration hash matches. |

Full receipts: data/m41/codex/experiment.json, discovery-final.json and kernel-shell-verbose-probe.json. The earlier discovery receipt treated unified_exec as a disableable tool; subsequent interpretation distinguishes the backend from permission-constrained execution. No NVIDIA input was sent until the revised complete gate passed.

## 8. FY2023-Q2 Pilot

```json
{
  "quarter": "FY2023-Q2",
  "analysis_run_id": 8,
  "snapshot_id": null,
  "gate": "FAIL",
  "context_hash": "82900ec0dff72eba344ec9bdf7e10b1215966ff0e40659e966060dfd6058e1ca",
  "calls": 6,
  "valid_calls": 4,
  "evidence": 143,
  "features": 0,
  "challenges": 0,
  "challenge_kinds": [],
  "rejected_claims": 3,
  "rejection_reasons": [
    "unsupported_speaker",
    "unsupported_speaker",
    "unsupported_speaker"
  ],
  "policy_hash": "af01d3fa799bdc6b64e894f7298ebdbb32afad2ad0b5c12cb07b94fdb1ba7638",
  "calls_status": [
    {
      "id": 31,
      "stage": "extract",
      "status": "valid",
      "failure": null
    },
    {
      "id": 32,
      "stage": "extract",
      "status": "valid",
      "failure": null
    },
    {
      "id": 33,
      "stage": "extract",
      "status": "valid",
      "failure": null
    },
    {
      "id": 34,
      "stage": "extract",
      "status": "valid",
      "failure": null
    },
    {
      "id": 35,
      "stage": "extract",
      "status": "invalid_or_unavailable",
      "failure": "provider_failure"
    },
    {
      "id": 36,
      "stage": "extract",
      "status": "invalid_or_unavailable",
      "failure": "provider_failure"
    }
  ]
}
```

The independent official account usage receipt reports 100% weekly usage consumed; reset 2026-09-19T22:18:10+10:00. Calls 35 and 36 retained generic provider_failure and hashes only, so their exact original error cause cannot be established from these records. No failure rows were retrospectively relabeled as quota failures. See usage-receipt.json.

A failed pilot halts further historical validation; no retry or promotion is implicit. Pilot output checks require valid provider calls, supported features, exact admitted evidence and required upside/downside/regime challenges. Any rejected candidate blocks automatic promotion pending assessment. This conservative gate is separate from frozen evidence admission: rejected claims are not promoted into official features.

## 9. Seven-Quarter Status

Pilot gate=FAIL. The pilot failed; remaining quarters and retries are stopped. Completed target quarters: 0/7. Historical Codex snapshots currently stored: 0; this count does not by itself equal cohort acceptance. Targets remain FY2023-Q2, FY2023-Q3, FY2024-Q1, FY2024-Q2, FY2025-Q4, FY2026-Q1, FY2027-Q2. No 26-quarter expansion.

## 10. Evidence / Feature Results

Codex evidence rows=143; features=0; rejected candidates=3. Reasons: {'unsupported_speaker': 3}. Real values, confidence, source references, support/contradiction metadata and provider calls are in research-outputs.json. Missing evidence remains unavailable, never fabricated neutral values. Claude's partial cohort stays separate and immutable. Every CLI call stores source IDs/hashes, prompt/schema versions, timestamps, response hashes and sandbox/approval/provider metadata.

## 11. Model Challenges

Stored challenge rows=0. Required upside/downside/regime and applicable anomaly/adjustment coverage is evaluated at pilot acceptance. Proposals remain advisory; they do not alter Quant, forecasts, valuation or Regime.

## 12. Repeatability

No repeated historical Codex analysis is counted before full cohort approval. Required fresh repeats remain FY2023-Q2 and FY2023-Q3 with fixed context, prompt, model, CLI and transport policy; compare evidence, feature direction/magnitude and challenges. Synthetic adversarial cases are not repeats.

## 13. Human Review

Actual Codex review status: {"required": 35, "completed": 0, "pending": [{"quarter": "FY2023-Q2", "category": "demand"}, {"quarter": "FY2023-Q2", "category": "supply"}, {"quarter": "FY2023-Q2", "category": "competition"}, {"quarter": "FY2023-Q2", "category": "product_cycle"}, {"quarter": "FY2023-Q2", "category": "management"}, {"quarter": "FY2023-Q2", "category": "anomalies"}, {"quarter": "FY2023-Q2", "category": "model_challenge"}, {"quarter": "FY2023-Q3", "category": "demand"}, {"quarter": "FY2023-Q3", "category": "supply"}, {"quarter": "FY2023-Q3", "category": "competition"}, {"quarter": "FY2023-Q3", "category": "product_cycle"}, {"quarter": "FY2023-Q3", "category": "management"}, {"quarter": "FY2023-Q3", "category": "anomalies"}, {"quarter": "FY2023-Q3", "category": "model_challenge"}, {"quarter": "FY2024-Q1", "category": "demand"}, {"quarter": "FY2024-Q1", "category": "supply"}, {"quarter": "FY2024-Q1", "category": "competition"}, {"quarter": "FY2024-Q1", "category": "product_cycle"}, {"quarter": "FY2024-Q1", "category": "management"}, {"quarter": "FY2024-Q1", "category": "anomalies"}, {"quarter": "FY2024-Q1", "category": "model_challenge"}, {"quarter": "FY2024-Q2", "category": "demand"}, {"quarter": "FY2024-Q2", "category": "supply"}, {"quarter": "FY2024-Q2", "category": "competition"}, {"quarter": "FY2024-Q2", "category": "product_cycle"}, {"quarter": "FY2024-Q2", "category": "management"}, {"quarter": "FY2024-Q2", "category": "anomalies"}, {"quarter": "FY2024-Q2", "category": "model_challenge"}, {"quarter": "FY2025-Q4", "category": "demand"}, {"quarter": "FY2025-Q4", "category": "supply"}, {"quarter": "FY2025-Q4", "category": "competition"}, {"quarter": "FY2025-Q4", "category": "product_cycle"}, {"quarter": "FY2025-Q4", "category": "management"}, {"quarter": "FY2025-Q4", "category": "anomalies"}, {"quarter": "FY2025-Q4", "category": "model_challenge"}], "correct_rate": null, "correct_plus_partial_rate": null, "unsupported_rate": null, "miss_rate": null, "rate_denominator": 0, "human_gate_complete": false, "expansion_requires_pm_approval": true}. The five-quarter by seven-category review set remains pending actual human verdicts. AI-generated commentary is not human review. Correct/partially_correct/unsupported/missed rates remain unavailable until real labels are supplied.

## 14. Quant Preservation

Original Quant, financial facts, forecasts, valuation and all 26 Regime states/IDs were verified unchanged by the post-pilot preservation audit. Frozen analysis contracts, source selection, guards and prior Claude audit rows are checked by the full M4.1 report generator. Codex is integrated only at AIProvider and CLI provenance/transport boundaries. SQLite: 226 passed, 1 skipped in 39.54s; PostgreSQL: 227 passed in 88.45s (0:01:28), original rows unchanged=True. Regression coverage includes Codex identity/auth, missing executable, no-gate refusal, sandbox/config flags, malformed JSON, timeout, tool/escalation interruption, provider separation and unchanged PIT/admission/Quant checks.
