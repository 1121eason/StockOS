# M4.1 Execution Report

Generated 2026-09-13T07:42:56.470609+00:00. **PARTIAL — M4.1 is not accepted; no M5 work.**

## 1. Provider Capability Table

| Provider | Executable / version | Runtime status |
|---|---|---|
| Claude primary | /Users/eason/.local/bin/claude / 2.1.251 (Claude Code) | Auth usable; latest live workflow quota_limited |
| Antigravity reviewer/fallback | /Users/eason/.local/bin/agy / 1.2.2 | ANTIGRAVITY_CLI_PIT_ISOLATION_UNSUPPORTED; ready=False |
| Legacy Gemini | /Users/eason/.local/bin/gemini / 0.59.0 | consumer_support_status=unsupported_current_environment; deprecated; no retry |
| Codex | Official subscription CLI experiment | See latest Codex PIT report below |

## 2. Authentication / Subscription Status

Official CLI subprocesses only. No OAuth/session tokens or credential-store contents are inspected, extracted, proxied, or copied by QVE. No API key is required. Antigravity authentication status: usable. No authentication or model discovery was repeated in this hardening run; the prior successful login was reused for one harmless schema/capability probe. Its requested model is gemini-3.1-pro-high; reasoning effort high; actual identity gemini-3.1-pro-high. Claude's latest known limit resets 2026-09-13 20:00 Australia/Brisbane. No claim that quota is already restored.

## 3. Seven-Quarter Completion

0/7 unique target quarters completed. Provider/model cohorts stay separate; no ensemble and no partial-Claude promotion.

| Provider | Requested model | Complete | Valid / attempted calls | Admitted evidence | Features |
|---|---|---:|---:|---:|---:|
| claude_cli | sonnet | 0/7 | 16/30 | 388 | 0 |
| antigravity_cli | unavailable | 0/7 | 0/0 | 0 | 0 |
| codex_cli | gpt-6-astra | 0/7 | 4/6 | 143 | 0 |

Targets: FY2023-Q2, FY2023-Q3, FY2024-Q1, FY2024-Q2, FY2025-Q4, FY2026-Q1, FY2027-Q2. A failed or unauthenticated attempt is never a completed quarter.

## 4. AI Feature Results

Real values, confidence, support/contradiction relationships and missing fields are exported in provider/model `*-outputs.json`. With no completed snapshots, feature output is unavailable. Missing is NULL, never neutral zero. FeatureSchemaV1 and polarity are unchanged.

## 5. Evidence Coverage

All admitted and rejected extraction rows are retained in cohort exports. Source IDs, block/span, hash and historical availability remain mandatory. Partial Claude evidence is immutable audit material. Evidence-backed feature rate below means linked admitted evidence, not a human semantic entailment verdict.

| Cohort | Provider failure rate | Schema failure rate | Extraction admission rejection rate | Evidence-backed feature rate |
|---|---:|---:|---:|---:|
| claude_cli / sonnet | 0.4666666666666667 | 0.0 | 0.039603960396039604 | None |
| antigravity_cli / unavailable | None | None | None | None |
| codex_cli / gpt-6-astra | 0.3333333333333333 | 0.0 | 0.02054794520547945 | None |

Call denominator includes actual provider calls and excludes recovery cache hits. Extraction rejection denominator is admitted evidence rows plus rejected extraction candidates. NULL denotes no measurable denominator. Historical Claude generic failure rows are not rewritten; the official quota receipt establishes the operational interruption, not analytical failure.

## 6. Model Challenges

Upside, downside, regime and applicable anomaly explanations remain required for acceptance. Actual kinds/counts: {"claude_cli/sonnet": {}, "antigravity_cli/unavailable": {}, "codex_cli/gpt-6-astra": {}}. Proposals are advisory and do not modify Quant or Regime state. No fabricated challenges fill incomplete runs.

## 7. Claude vs Antigravity Comparison

0 available exact-PIT-context comparisons. Cross-provider agreement is diagnostic and does not count as repeatability or pick a winner. Evidence Jaccard, sign agreement, magnitude differences, missing fields and challenge overlap are exported when both completed snapshots exist.

## 8. Human Review Results

0 actual human categories reviewed. Existing five-quarter × seven-category cards are exported separately for each provider. Verdicts, reviewer, timestamp and evidence references remain empty until a human supplies them. Correct Rate, Correct + Partially Correct Rate, Unsupported Rate and Miss Rate remain NULL without actual reviews. Provider/model provenance is explicit in the cards and linked immutable run ID.

## 9. Unsupported / Hallucination Results

Rejection reasons by cohort: {"claude_cli/sonnet": {"unsupported_speaker": 2, "span_not_in_source": 14}, "antigravity_cli/unavailable": {}, "codex_cli/gpt-6-astra": {"unsupported_speaker": 3}}. Source-absent claims, including latent future knowledge, are rejected by unchanged admission rules. Exact quote matching alone does not prove semantic support or zero hallucinations; human assessment remains outstanding.

## 10. Repeatability Results

0 completed same-provider/model/context comparisons. Fresh repeated model calls are required; recovery reuse and cross-provider comparison do not count. Insufficient quota/authentication is operational unavailability, not semantic instability.

## 11. PIT / Leakage Results

Frozen prompts/contracts/guards/source-selection/Quant-context hashes unchanged: True. Existing PIT cutoff and stock-price/outcome exclusion tests remain authoritative. No Antigravity historical prompt is sent until its structured output and zero-tool discovery contract passes. Live Antigravity leakage acceptance is pending if no completed live run exists.


## Antigravity PIT Isolation

Gate: **FAIL**. Stop code: `ANTIGRAVITY_CLI_PIT_ISOLATION_UNSUPPORTED`.
The official CLI loaded `qve-pit-analyst`; the empty `tools: []` declaration did not remove the advertised capabilities. Antigravity remains operationally available but is **not approved for QVE historical replay**. No further model calls were made after this failed gate.

| Property | Recorded value |
|---|---|
| Requested / actual agent | qve-pit-analyst / qve-pit-analyst |
| Workspace safety-agent hash | fe67c5f94f4d40c1ffe28dfdf4ec15aa156590e0dc55ccea5a02a52529d44aad |
| Actual runtime agent definition hash | 1b9c846be4a034dd97e99c6d2292445cdddcb5b3c16c5a10ff0097514c441021 |
| CLI / requested model / actual model | 1.2.2 / gemini-3.1-pro-high / gemini-3.1-pro-high |
| Forbidden advertised tools | 56 (every advertised name except finish is disallowed) |
| Permission mode | CLI_default_no_permission_bypass |
| Sandbox enabled | False |
| Harmless probe external tool events | 0 |
| Harmless probe observed tool names | ['finish'] |
| Pilot FY2023-Q2 | NOT RUN: isolation prerequisite failed |
| Seven-quarter completion | 0/7 |

Before hardening (previous qve-advisory probe): `ask_custom_permission, ask_permission, ask_question, browser_click_element, browser_drag_pixel_to_pixel, browser_get_dom, browser_get_network_request, browser_input, browser_list_network_requests, browser_mouse_down, browser_mouse_up, browser_move_mouse, browser_press_key, browser_refresh_page, browser_resize_window, browser_scroll, browser_scroll_dom, browser_select_option, browser_subagent, call_mcp_tool, capture_browser_console_logs, capture_browser_screenshot, click_browser_pixel, command_status, define_subagent, delete_knowledge, execute_browser_javascript, find_by_name, finish, generate_image, grep_search, invoke_subagent, list_browser_pages, list_dir, list_permissions, list_resources, manage_inbox, manage_subagents, manage_task, multi_replace_file_content, notebook_edit, notebook_execution, open_browser_url, read_browser_page, read_resource, read_url_content, replace_file_content, run_command, schedule, search_web, sed_file, send_command_input, send_message, view_file, wait, wait_5_seconds, write_to_file`.

After hardening (qve-pit-analyst, tools: []): `ask_custom_permission, ask_permission, ask_question, browser_click_element, browser_drag_pixel_to_pixel, browser_get_dom, browser_get_network_request, browser_input, browser_list_network_requests, browser_mouse_down, browser_mouse_up, browser_move_mouse, browser_press_key, browser_refresh_page, browser_resize_window, browser_scroll, browser_scroll_dom, browser_select_option, browser_subagent, call_mcp_tool, capture_browser_console_logs, capture_browser_screenshot, click_browser_pixel, command_status, define_subagent, delete_knowledge, execute_browser_javascript, find_by_name, finish, generate_image, grep_search, invoke_subagent, list_browser_pages, list_dir, list_permissions, list_resources, manage_inbox, manage_subagents, manage_task, multi_replace_file_content, notebook_edit, notebook_execution, open_browser_url, read_browser_page, read_resource, read_url_content, replace_file_content, run_command, schedule, search_web, sed_file, send_command_input, send_message, view_file, wait, wait_5_seconds, write_to_file`.

Adversarial search_web, read_url_content, view_file, run_command, and define_subagent prompts: **NOT RUN**. Section 11 of the supplied hardening request explicitly requires STOP when forbidden capabilities remain. Successful external retrieval count for these unexecuted tests is **unavailable**, not zero. The harmless probe observed only finish tool events; that does not establish that external retrieval is impossible or that non-workspace access is disabled.

Authentication, model execution and schema output succeeded; capability isolation failed. No NVIDIA quarter data, repository, database, archive, price/outcome file, or Git history was copied into the temporary working directory. Existing HOME is passed only for official CLI session handling; no credential files were read by QVE. No OS denial of home access is claimed. No permission bypass flag was used. Frozen PromptSetV1 instructions remain unchanged and occur once in the runtime agent after the static safety boundary; the workspace template contains safety instructions only.

Full normalized metadata, prompt/source-envelope hashes, advertised names and raw-output hash: `data/m41/antigravity/pit-isolation.json`. Agent hashes use the existing QVE digest function over exact definition text; the runtime hash also includes the supplied instructions. The synthetic source envelope is empty. Original probe receipts are retained. Repeatability and actual human review remain pending; no pilot/quarter outputs were fabricated.


## 12. Quant Preservation

Pre-existing AI audit rows unchanged: True. Existing Quant, financial facts, DCF/Reverse DCF, valuation and 26 Regime states/IDs preservation receipt is retained at data/m41/report/preservation.json. AI imports remain advisory. CLI integration alters transport/retry handling only, not frozen financial rules.

## 13. Test Results

SQLite: 226 passed, 1 skipped in 39.54s. PostgreSQL: 227 passed in 88.45s (0:01:28); original PostgreSQL rows unchanged=True. Latest test receipts are under data/m41/codex and data/m41/postgresql. Synthetic subprocess and corpus fixtures are never counted as real NVIDIA runs. Tests cover unavailable auth/executable, malformed output, timeout, quota, injection, cohort separation, identical-context comparison, future-claim rejection and immutable rows.

## 14. Provider Operational Limitations

Claude: quota_limited at last real attempt. Antigravity: ANTIGRAVITY_CLI_PIT_ISOLATION_UNSUPPORTED; required real readiness=False. Runtime help is emitted on stderr by agy 1.2.2 and captured only for the explicit help command. Version changes fail closed. Antigravity tool/customization isolation must be verified from its real stream initialization; advertised flags and synthetic tests alone are insufficient. Legacy Gemini consumer access remains unsupported and will not be retried. Codex transport isolation passed, but its single historical pilot failed and further historical execution is stopped. API routes remain inactive.

## 15. Updated M4.1 Acceptance Criteria

| Gate | Status | Criterion |
|---|---|---|
| G1 | FAIL | Accepted live provider completes snapshots |
| G2 | FAIL | Seven representative quarters completed |
| G3 | FAIL | Real feature evidence admission |
| G4 | FAIL | Required challenges |
| G5 | FAIL | Two same-provider repeat comparisons |
| G6 | FAIL | Five-quarter human review complete |
| G7 | FAIL | Human unsupported/partial/missed findings measured |
| G8 | PASS | Quant and prior AI preserved |
| G9 | PASS | PIT policy and source boundaries preserved |

Original AC1–AC16, carried forward with the authorized provider hierarchy:

| Criterion | Status | Evidence / remaining requirement |
|---|---|---|
| AC1 | PASS | Official subscription CLI real structured calls |
| AC2 | PASS | No API key required |
| AC3 | PASS | No credential extraction or token reuse |
| AC4 | FAIL | 0/7 completed quarters |
| AC5 | PARTIAL | Evidence admission observed; human semantic review pending |
| AC6 | PARTIAL | Historical source availability and completed coverage |
| AC7 | PASS | Frozen stock-price/outcome exclusion tests |
| AC8 | PARTIAL | Required challenge coverage; no Quant mutations |
| AC9 | FAIL | 0/35 actual human categories |
| AC10 | PARTIAL | Separate operational/schema/admission metrics; human rates unavailable |
| AC11 | FAIL | Human semantic support and hallucination assessment |
| AC12 | FAIL | 0/2 same-provider repeatability comparisons |
| AC13 | PASS | SQLite/PostgreSQL tests |
| AC14 | PASS | Bounded operational failures and independent Quant engine |
| AC15 | PASS | Antigravity rejected for PIT; Gemini deprecated; Codex transport passed, pilot failed |
| AC16 | PASS | No M5, trading labels or return optimization |

No provider diversity requirement blocks acceptance if Claude alone passes all quality gates. Seven quarters and actual human review remain mandatory.

## 16. Recommendation

**Continue with Claude only once primary quota is available.** The installed Antigravity 1.2.2 contract is unsupported for QVE PIT replay (ANTIGRAVITY_CLI_PIT_ISOLATION_UNSUPPORTED); this hardening run stopped at the required gate. Do not repeat authentication or send historical inputs to this unsupported configuration. This is an operational fallback decision, not rejection for analytical quality. Do not expand to 26 quarters, begin M5, introduce trading labels or optimize returns before the updated gate and PM acceptance.

## AGY PIT Quarantine V2 — latest experiment

ANTIGRAVITY_CLI_PIT_QUARANTINE_FAILED. Six synthetic cases completed, settings restored, no historical inputs sent. A-D were terminated at ACTIVE tool events; external completion remains unknown. E claimed subagent retrieval and emitted unsupplied page text without a tool event; provenance is unverified. F returned unavailable. No pilot or seven-quarter execution. Previous V1 failures above remain historical evidence.

Full Q1-Q10 findings, counters and limitations: [M4.1 AGY PIT Quarantine Report](M4_1_AGY_PIT_QUARANTINE_REPORT.md). The production provider remains unapproved for historical replay; Claude remains the accepted primary route once quota permits.

## Codex CLI PIT experiment — latest continuation

Codex CLI synthetic isolation gate PASS; FY2023-Q2 pilot gate FAIL. Provider cohorts remain separate. See [Codex CLI PIT Experiment Report](M4_1_CODEX_CLI_PIT_EXPERIMENT_REPORT.md) for C1-C12, native sandbox probes, actual pilot rows, provenance and remaining gates. No M5.
