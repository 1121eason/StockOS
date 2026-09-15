# Antigravity CLI — M4.1

Official executable: `/Users/eason/.local/bin/agy`, installed version 1.2.2. The installer verifies the official download checksum. CLI help confirms streaming stdin/stdout, JSON schema, model and reasoning-effort flags. Google authentication is managed only by the official executable; QVE never opens credential stores or copies session tokens.

Current status: official subscription login is usable. The selected runtime-listed model is gemini-3.1-pro-high, effort high. Real constant-input schema probes returned SUCCESS with {"ok":true}, but both advertised the full external-tool registry under tools: [] and tools: [finish]. The adapter fails closed with isolation_contract_failure. No financial corpus has been sent. No additional login is needed; the tool/customization isolation contract must be resolved before live quarter execution.

The two immutable probe receipts are provider-check.json (latest normalized status) and provider-check-finish-only.json, with the first probe retained in provider-check-initial-tools.json. They contain no credential values.

```sh
.venv/bin/qve ai-provider-check --provider antigravity_cli
.venv/bin/qve ai-run-validation-set --ticker NVDA --provider antigravity_cli --repeat
.venv/bin/qve ai-compare-providers --ticker NVDA --quarter FY2027-Q2 --provider-a claude_cli --provider-b antigravity_cli
```

The adapter implements the existing AIProvider stages and requires a real constant JSON probe with no tools exposed before analysis. Each call creates a controlled temporary agent definition using frozen system instructions, disables inherited customizations and slash expansion, supplies one NDJSON user message on stdin, validates terminal SUCCESS plus structured output, and removes temporary files. Actual external-tool exclusion must be verified live before quarter analysis; synthetic tests do not establish provider readiness.

Versions other than 1.2.2 fail closed pending validation. Every result records executable path, CLI version, requested/actual model, reasoning effort, timestamps, prompt/source/schema identifiers, hashes and failure category. No silent interactive/API fallback. Operational quota exhaustion is distinct from schema and semantic admission failure. Existing partial Claude evidence and completed snapshots are immutable. Recovery is restricted to identical provider/model/version/context/prompt; repeats use fresh model calls.

Claude remains primary. Antigravity is an independent reviewer or temporary fallback. Gemini consumer route is deprecated; Codex remains inactive. Cross-provider comparisons require completed snapshots at an identical PIT context and never count as repeatability or create an ensemble. Human review and PM acceptance are mandatory before 26-quarter expansion. No M5.

Official documentation:
- https://antigravity.google/docs/cli/install/
- https://antigravity.google/docs/cli/headless/
- https://antigravity.google/docs/cli/commands/agents/


## PIT hardening decision — 2026-09-13

The explicit workspace agent `.agents/agents/qve-pit-analyst/agent.md` declares `tools: []`, no subagents, MCP, plugins or skills, and disabled customization inheritance. The adapter explicitly selects it and rejects a mismatched reported identity. A fresh nonfinancial live probe confirmed the requested agent and gemini-3.1-pro-high, but advertised 57 tools (56 disallowed; finish alone is allowlisted).

**ANTIGRAVITY_CLI_PIT_ISOLATION_UNSUPPORTED**. Stop: no NVIDIA pilot or cohort, no further adversarial model requests. Such adversarial tests are NOT RUN, not passed. Authentication and schema success do not imply PIT safety. Metadata is in `data/m41/antigravity/pit-isolation.json`. Claude remains the accepted primary route once quota is available. No authentication was repeated.


Latest M4.1 experiment: AntigravityTransportPolicyV2-PITQuarantine failed (ANTIGRAVITY_CLI_PIT_QUARANTINE_FAILED). Six synthetic cases completed; original settings restored. A-D terminated at ACTIVE tool steps without proof of zero external success. E returned an unsupported subagent-retrieval claim without a tool event; F returned unavailable. No NVIDIA input or pilot. See docs/M4_1_AGY_PIT_QUARANTINE_REPORT.md. Prior V1 receipts remain unchanged.
