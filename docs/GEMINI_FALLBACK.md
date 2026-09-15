# M4.1 Gemini fallback

Activated by explicit user instruction after Claude session quota exhaustion. Official Gemini CLI: 0.59.0. Requested model: gemini-2.5-pro. Actual model is recorded from response stats only. Google-session credentials are managed solely by the official CLI.

Current blocker: the official Google service returns IneligibleTierError / UNSUPPORTED_CLIENT for Gemini Code Assist for individuals and directs migration to Antigravity. Installation and transport tests passed, but Gemini cannot execute. Do not repeatedly request login or retry financial quarters while this rejection persists. No API fallback or product migration has been authorized.

After service eligibility is resolved, from StockOS:

```sh
.venv/bin/qve ai-provider-check --provider gemini_cli
.venv/bin/qve ai-run-validation-set --ticker NVDA --provider gemini_cli --repeat
.venv/bin/qve ai-review-status --provider gemini_cli
```

The constant JSON probe must pass before analysis. Every call uses a new temporary directory, strict JSON output, no tools/MCP/extensions/hooks/skills, and a trusted system prompt. macOS sandbox-exec denies default GEMINI.md/MEMORY.md/AGENTS.md reads: CLI 0.59.0 otherwise retains those default filenames despite empty context settings. Other CLI versions/platforms fail closed pending validation.

Seven-quarter results and human review cards are provider-specific under data/m41/report/gemini. Independent repeats always make fresh calls. Recovery reuses only exact validated extraction responses from incomplete runs with the same provider, model, version and PIT context. Human verdicts stay empty until actual review.

Official references: https://geminicli.com/docs/get-started/installation/ and https://geminicli.com/docs/reference/configuration/.
