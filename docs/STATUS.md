# StockOS status

## 2026-10-21 source integration

The [four-layer progress and branch integration report](PROGRESS_REPORT_2026_10_21.md) records the integrated source baseline, conflict decisions, offline test results, and remaining acceptance work. NVIDIA financial research and Regime retain their existing milestone status; AI formal acceptance, investment-decision acceptance, and long-term automation remain incomplete.

## Preserved historical execution status

Provider availability, quota, login, and run counts below are historical observations. They were not refreshed by the source integration.

M4.1 Antigravity integration is implemented; live validation remains blocked by the Antigravity tool-isolation contract. Antigravity CLI 1.2.2 is installed at /Users/eason/.local/bin/agy. Runtime capability discovery confirms the required flags. Official login is now usable and Gemini 3.1 Pro High returned valid structured JSON. Two real constant-input probes exposed the full tool registry despite tools: [] and tools: [finish] configurations. The adapter correctly reports isolation_contract_failure and refuses historical financial inputs. No financial context has been sent to Antigravity. No repeated login is needed.

Claude remains primary and quota_limited at the last real execution (reset reported 2026-09-13 20:00 Australia/Brisbane). Its 388 admitted partial evidence rows remain immutable; completed quarters 0/7, actual human reviews 0/35. Legacy Gemini consumer route is deprecated; Codex transport isolation passed; its historical pilot failed. API providers remain inactive.

Updated commands, provider/model cohort separation, diagnostic comparison, bounded operational errors and tests are in place. Frozen financial prompts/schema/admission/PIT rules are unchanged. See MILESTONE_4_1_EXECUTION_REPORT.md and ANTIGRAVITY_CLI.md. No M5 or 26-quarter expansion.


M4.1 PIT hardening (2026-09-13): qve-pit-analyst correctly loaded with tools: [], but CLI 1.2.2 advertised 56 disallowed capabilities. ANTIGRAVITY_CLI_PIT_ISOLATION_UNSUPPORTED; stopped before NVIDIA inputs, pilot and adversarial execution. Completion remains 0/7, human review 0/35, repeats pending. See the dedicated Antigravity PIT Isolation section in MILESTONE_4_1_EXECUTION_REPORT.md.


Prior M4.1 experiment: AntigravityTransportPolicyV2-PITQuarantine failed (ANTIGRAVITY_CLI_PIT_QUARANTINE_FAILED). Six synthetic cases completed; original settings restored. A-D terminated at ACTIVE tool steps without proof of zero external success. E returned an unsupported subagent-retrieval claim without a tool event; F returned unavailable. No NVIDIA input or pilot. See docs/M4_1_AGY_PIT_QUARANTINE_REPORT.md. Prior V1 receipts remain unchanged.

Latest M4.1 Codex experiment: C1–C12 transport isolation PASS; one FY2023-Q2 pilot FAIL (run 8, six calls, four valid, 143 admitted evidence, three rejected unsupported_speaker candidates, zero features/challenges/snapshots). Further historical validation stopped under the original pilot-failure rule; completed quarters 0/7, human reviews 0/35, no repeats. Independently observed current Codex weekly usage 100%; the two failed call receipts retain generic provider_failure, not a proven quota diagnosis. Post-pilot Quant/Regime/archive preservation passed. SQLite 226 passed / 1 skipped; PostgreSQL 227 passed. See M4_1_CODEX_CLI_PIT_EXPERIMENT_REPORT.md and MILESTONE_4_1_EXECUTION_REPORT.md.
