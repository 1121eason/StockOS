# Quarterly Fundamental Valuation Engine — NVIDIA / Milestone 4

Executable, deterministic quarterly financial research engine. **Quant calculates. AI interprets.**
NVDA only. No trading signals, fitted thresholds, brokerage connection or claimed returns.

Current source integration and four-layer progress: [2026-10-21 progress report](docs/PROGRESS_REPORT_2026_10_21.md). Branch integration does not constitute AI, investment-decision, or production acceptance.

**Source-only checkout:** Runtime NVDA databases and original research artifacts are not included. Historical milestone evidence below describes separate local runs, not data available in a fresh clone. The [isolated offline research workflow](docs/RESEARCH_WORKSPACE.md) imports explicitly supplied bundles into a separate store; [UI instructions](UI_START_HERE.md) explain its read-only view. Missing inputs stay unavailable. The [backtest timing audit](docs/BACKTEST_TEMPORAL_AUDIT.md) documents reconstruction-only classification and execution limitations.

**M1.1 Final Closure: PM accepted.** Read [the preserved closure report](docs/MILESTONE_1_1_FINAL_CLOSURE_REPORT.md). Two real SEC runs created 112 filings, 1,938 facts and 65 documents on the first run, and zero new records on the second. All 26 valuation dates have eligible shares and market cap; all three PM gates pass. PM accepts minute-level availability and explicitly labeled research-reconstructed prices. Independent raw-price vendors and Wall Street consensus are not required. M2 implementation and evidence are described below.

## Milestone 4 AI Analyst

M1–M3.1 have PM Review pass. M4 adds evidence-first qualitative interpretation and advisory challenges; it does not calculate forecasts, valuation or regime. [Method](docs/AI_ANALYST_METHOD.md), [current report](docs/MILESTONE_4_EXECUTION_REPORT.md). The infrastructure is tested; actual historical AI results and human review are still pending provider setup. Missing inputs are never replaced with fixture results.

Set `QVE_AI_PROVIDER`, `QVE_AI_MODEL`, `QVE_AI_MODEL_VERSION` and `OPENAI_API_KEY` locally for the OpenAI adapter. The actual response model must match the pinned version. Another provider can implement AIProvider. Never commit or paste keys.

```sh
uv run qve init-db
uv run qve ai-analyze --ticker NVDA --quarter FY2027-Q2 --prepare-only
uv run python scripts/prepare_m4.py --execute
uv run qve ai-analyze --ticker NVDA --quarter FY2027-Q2
uv run qve ai-history --ticker NVDA
uv run qve ai-features --ticker NVDA --as-of 2026-08-27T13:30:00Z
uv run qve ai-challenges --ticker NVDA --as-of 2026-08-27T13:30:00Z
uv run qve ai-evidence --analysis-run <id>
uv run qve ai-export-recording --analysis-run <id> --out recording.json
uv run qve research-view --ticker NVDA
```

`prepare_m4.py --execute` starts only the seven representative quarters. Expand with `--all-quarters` after output review. Human review imports use `qve ai-review-import <completed-review.json>` with actual reviewer identity. A blank template is not a completed review.

## Milestone 3.1 confidence and transition contract

M3 and M3.1 now have PM Review pass under the M4 work order. Read [the 12-section report](docs/MILESTONE_3_1_EXECUTION_REPORT.md), [method](docs/REGIME_METHOD.md), and [mandatory output contract](docs/REGIME_OUTPUT_CONTRACT.md). Evidence, active-input quality and history are separately persisted; confirmed and candidate states travel together with transition status, probabilities and Cycle Score. Scores/prototypes/core thresholds remain frozen. Original M3 reports and [V1 method](docs/archive/REGIME_METHOD_V1.md) remain historical evidence.

```sh
uv run qve init-db
uv run python scripts/run_m31.py
uv run qve regime --ticker NVDA --as-of 2022-11-17T14:30:00Z --json-output
uv run qve regime-history --ticker NVDA
uv run qve regime-transitions --ticker NVDA
uv run qve regime --ticker NVDA --policy-version RegimePolicyV1
```

CLI defaults to RegimePolicyV1.1. Legacy V1 requires explicit selection. For a relocated delivery bundle without pre-M3.1 backups, use `scripts/run_m31.py --skip-preservation-audit`; source hashes and repeat-replay checks still run, and original-row preservation receipts are included.

## Milestone 2 research

M1.1 is the PM-accepted data contract. M2 adds immutable deterministic GAAP forecasts, financial-error evaluation and historical forward valuation. Read [Forecast method](docs/FORECAST_METHOD.md), [Valuation method](docs/VALUATION_METHOD.md) and [M2 execution report](docs/MILESTONE_2_EXECUTION_REPORT.md). All reconstructed historical forecasts are labeled `research_reconstructed_internal`. There are no trading recommendations or return-optimized coefficients.

```sh
uv run qve init-db
uv run python scripts/run_m2.py --repeat
uv run qve forecast --ticker NVDA --as-of 2023-05-25T09:30:00-04:00
uv run qve forecast-revisions --ticker NVDA
uv run qve forecast-accuracy --ticker NVDA --as-of 2026-09-12T00:00:00Z
uv run qve valuation --ticker NVDA --as-of 2023-05-25T09:30:00-04:00
uv run qve dcf --ticker NVDA --as-of 2026-08-27T09:30:00-04:00
uv run qve reverse-dcf --ticker NVDA --as-of 2026-08-27T09:30:00-04:00
```

`forecast-history` and `valuation-history` replay A/B/C across both checkpoints. Add `--json-output` to the single-snapshot forecast/valuation/DCF commands for complete provenance. `forecast --quarter ...` retains the explicitly legacy M1 baseline interface; omit `--quarter` for ForecastPolicyV1. History is chronological so empirical intervals can use only already realized prior financial errors. The label database is opened only by evaluation, never by forecasting. Missing inputs stay unavailable.

Core migration: `0005_research`; labels migration: `0003_forecast_outcomes`. The M1.1 archives remain unchanged. Stop after M2; no subsequent milestone is included.

## M1/M1.1 setup and preserved interfaces

## Quick start

Python 3.12+ and `uv`:

```sh
uv sync --locked
cp .env.example .env
uv run qve init-db
uv run qve ingest-nvda-ir
uv run qve ingest-prices --start 2020-01-01 --end 2026-09-11
```

To configure the SEC download identity locally, then download the SEC records:

```sh
uv run qve configure-sec
uv run python scripts/close_m11.py --live-sec
```

This is an HTTP identification header, not a password/API key. It is sent to SEC and never hard-coded or committed. Missing identity produces an explicit error and an ingestion audit record.

This workspace already has a populated SQLite database and content-hashed official releases in `data/` (ignored by Git). Use `.venv/bin/qve` directly here if `uv` is not on PATH.

## Reproduce the research outputs

```sh
uv run qve build-quarterly-snapshots --ticker NVDA --as-of 2026-09-12T00:00:00-04:00
uv run qve calculate-features --ticker NVDA --as-of 2026-09-12T00:00:00-04:00
uv run qve validate-data --ticker NVDA --as-of 2026-09-12T00:00:00-04:00
uv run qve show-quarter --ticker NVDA --quarter FY2027-Q2 --as-of 2026-08-27T09:30:00-04:00
uv run qve show-quarter --ticker NVDA --quarter FY2024-Q1 --as-of 2023-05-25T09:30:00-04:00 --json-output
uv run qve forecast --quarter FY2027-Q2 --as-of 2026-08-27T09:30:00-04:00
uv run qve value-quarter --quarter FY2027-Q2 --as-of 2026-08-27T09:30:00-04:00
uv run qve build-labels --as-of 2026-09-12T00:00:00-04:00
uv run qve coverage
```

Historical forecasting is explicitly marked `historical_replay`. It cannot become an actual historical analyst/engine estimate merely by choosing an old cutoff. `value-quarter` uses explicitly labeled split-reconstructed as-traded prices after M1.1 hardening. Ratios requiring absent eligible shares or financial inputs remain NULL. Annual forward valuation is deferred, and observed Wall Street consensus is not required for M1.1 closure.

Offline re-ingestion of the bundled local cache (same source bytes, verified SHA-256):

```sh
uv run qve replay-ir-cache --manifest data/ir-manifest.json
```

## Validation

```sh
uv run pytest -q
uv run ruff check src tests migrations
uv run ruff format --check src tests migrations
uv run mypy src
```

Tests run offline, including synthetic SEC HTTP responses, migrations, immutable records, PIT queries, quarterly/YTD conversion, calendar boundaries, forecasting and feature/label isolation. Closure tests also cover share availability, cover-page extraction, both splits, market-cap invariance and missing EV components. `scripts/validate_closure_postgres.py` applies current migrations and runs the closure workflow and full test suite on the isolated PostgreSQL instance. Current results are recorded in the closure report. The plain SQLite run skips only the PostgreSQL-specific live migration check.

## Architecture

Official bytes → source documents → append-only financial facts → PIT quarter reconstruction → deterministic features / baseline forecasts → valuation snapshots.

Price data → a separate label pipeline → **separate label database**. Feature/forecast modules query financial facts and guidance, never labels.

See [Architecture](docs/ARCHITECTURE.md), [Point in time](docs/POINT_IN_TIME.md), [Data dictionary](docs/DATA_DICTIONARY.md), [Decisions](docs/DECISIONS.md), [Status](docs/STATUS.md) and [Latest-quarter source check](docs/MANUAL_VALIDATION.md).

## M1/M1.1 historical limitations

- M1.1 verifies 26 issuer-distributed releases to the minute. Scope-specific evidence supplies conservative end-of-minute availability; the original IR website dates remain date-only.
- SEC live ingestion covers all 26 target filing quarters; the contact identity stays in the local environment and is excluded from deliveries. Reconciliation retains one monetary conflict, 74 unknown-basis pairs and 77 unpaired IR observations. The unresolved SEC candidates are not selected in the reviewed snapshots; this does not approve them for other uses.
- Older liquid-asset aggregates are retained. Where ending cash is explicitly in the cash-flow statement, securities can be derived with both fact IDs. Restricted-cash-only disclosures remain unfilled.
- Split-crossing EPS uses verified presentation bases and the formal corporate-action model. Unverified bases remain unavailable.
- Yahoo bootstrap prices are current-vintage split-adjusted OHLC. Historical valuation uses their explicitly labeled split reconstruction; an independently observed raw-price archive remains absent. Dividends are not included in price-return labels.
- Historical annual forecasts, final DCF assumptions, regime classifier, Opportunity Score and buy/sell rules are outside this milestone.


## Reproduce M1.1 evidence

With the local data bundle installed, run from this project directory:

```sh
uv run python scripts/harden_m11.py
uv run qve guidance-coverage
uv run qve show-quarter --quarter FY2024-Q1 --as-of 2023-05-24T16:19:59-04:00
uv run qve show-quarter --quarter FY2024-Q1 --as-of 2023-05-24T16:21:00-04:00
uv run qve value-quarter --quarter FY2024-Q1 --as-of 2023-05-25T09:30:00-04:00
```

The first query intentionally has no new-quarter data. Historical pre-closure reports in `data/m11/report/` retain the original timestamp/guidance matrices, basis checks and PM gate results. Current closure acceptance and latest-known-share semantics are reported in `data/m11-closure/report/`. All first-open valuations retain source fact IDs and archived price hashes.

## Final closure and PIT shares

Use `uv run python scripts/close_m11.py` for offline closure reports under `data/m11-closure/report/`.
Use `--live-sec` after configuring the SEC identity to run actual SEC ingestion twice and regenerate reconciliation, share coverage and all three PM gates. New share observations are append-only; market cap uses the latest eligible economic-date observation, then source priority and eligible revision. Weighted-average diluted shares are never substituted.

```sh
uv run qve known-shares --as-of 2023-05-25T09:30:00-04:00
uv run qve known-shares --as-of 2023-05-25T09:30:00-04:00 --basis-date 2024-06-10
uv run python scripts/report_closure_m11.py
```

The second query explicitly requests a comparable split basis; valuation uses its own historical as-traded date. EV retains the dates of last known cash/debt balances and lists missing components. Old M1.1 reports and archives are historical evidence; the closure report is the current acceptance record.

The PostgreSQL test instance uses a dedicated `stockos-m11-postgres` container at `127.0.0.1:55439`; it can be restarted with `docker start stockos-m11-postgres`. Final core and label databases are `qve_verified` and `qve_labels`. Local test authentication uses the isolated container's trust setting, not production credentials. Run `uv run python scripts/validate_postgres_m11.py` for the full live workflow and tests. Source and data review archives are stored separately under `artifacts/`; `.env` and runtime caches are excluded.

## M4.1 subscription CLI

See [CLI setup and execution](docs/CLI_PROVIDER_METHOD.md) and the [M4.1 execution report](docs/MILESTONE_4_1_EXECUTION_REPORT.md). Claude subscription login is required; API keys are optional. Seven-quarter real validation and actual human review gate Final Pass.
