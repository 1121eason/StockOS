# Milestone 1 status — 2026-09-12

## Completed

- Executable Python package, locked dependencies, CLI, SQLAlchemy schema and separate core/label Alembic migrations.
- Append-only financial facts, immutable forecasts/assumptions/quarterly snapshots/features, raw-document SHA-256 provenance.
- SEC submissions/companyfacts adapter with mocked HTTP integration and explicit missing-identity failure.
- Live NVIDIA official-release ingestion, checked offline replay and duplicate prevention.
- 26 consecutive quarters, FY2021 Q1–FY2027 Q2; no missing quarter in the target range.
- 692 reported facts across 30 metric names; revenue, COGS, gross profit, operating expenses, R&D, SG&A, operating income, net income, EPS, AR, inventory, assets, AP, equity, OCF, CapEx, SBC and diluted weighted-average shares in every quarter.
- 72 structured guidance items from 18 quarters; 79 historical market-platform observations.
- 1,682 daily price bars; 26 outcome-label records in a separate database. Immature horizons are NULL.
- 21 features per quarter (546 rows), with approximation/source metadata and deterministic anomaly flags.
- Two forecast snapshots (one historical replay and one current run), two assumption sets, one valuation snapshot with unavailable ratios explicitly NULL.
- Latest-quarter official-source cross-check: 18/18 numeric checks pass. Accounting validation: 52 checks, zero mismatches.
- Offline ingestion repeat: 0 facts created, 692 identical facts skipped; source/fact/guidance/segment counts remain unchanged.

## In Progress / awaiting input

SEC **live** ingestion has not run successfully. `SEC_USER_AGENT` is absent; no contact identity was invented. The adapter refuses the network call, records the failed run, and explains the missing configuration. **Current database has zero SEC filings.** Official NVIDIA releases are the actual financial data source in this deliverable.

## Data Quality Issues

Current database contains 142 explicit issues, not 142 erroneous numbers:

| Issue | Count | Meaning |
|---|---:|---|
| Publication time missing | 26 | Exact intraday release time unavailable; conservative next-midnight ET bound |
| Missing metric | 84 | Breakdown below; no zero filling |
| FCF definition difference | 23 | NVIDIA additionally deducts equipment/intangible principal payments |
| Guidance unparsed | 8 | Early outlook wording outside strict parser templates; source bytes retained |
| Ingestion failure | 1 | SEC user-agent identity missing before network access |

Missing metric observations: separate cash 24; separate marketable securities 24; period-end shares 26; current debt 5; consequently total debt 5. The combined cash-and-marketable-securities line is preserved for those 24 older quarters. Absent current debt is not assumed to be zero.

Structured guidance is unavailable for FY2021 Q1–Q4 and FY2022 Q1–Q4; raw official releases remain available. Market-platform extraction is selective and sometimes rounded; Compute & Networking / Graphics reporting-segment tables are not yet normalized.

The first four quarters lack the prior-year reference quarter needed for YoY features. First-quarter DSO uses the documented ending-AR approximation. EPS changes spanning the 2021/2024 splits remain NULL pending basis reconciliation.

## Known Gaps

1. Exact first-public timestamps and independently archived source vintages have not been established. The query engine is cutoff-safe under its documented conservative availability policy, but intraday historical completeness is not accepted.
2. No live SEC reconciliation or original SEC filing-document extraction has been completed without the required identity.
3. Yahoo bootstrap OHLC are current-vintage split-adjusted prices, not contemporaneous unadjusted prices. Real historical valuation multiples remain NULL; weighted-average shares are not substituted for period-end shares.
4. No genuine historical annual forecast vintages exist here, so FY1/FY2 forward P/E remains NULL. Historical replays are never counted as estimates that actually existed at the time.
5. PostgreSQL schema and migration SQL compile; no live PostgreSQL server test was performed. Local runtime/tests use SQLite.
6. GICS fields/confidence remain NULL without verified classification evidence. AI and regime tables are deliberately empty.
7. No strategy backtest, parameter optimization, final fair value, final Opportunity Score or buy/hold/sell model has been implemented. The outcome data and leakage boundary are prepared only.

## Tests

49 pytest tests passed, zero warnings, zero known failures. Ruff lint/format and mypy pass. Covered: formulas, GAAP guidance, date precision, quarter/YTD/annual conversion, source conflicts/restatements, immutable rows, SEC HTTP ingestion/idempotency, SQLite migrations, PostgreSQL offline SQL, market adapter, label maturity and physical feature/label isolation.

## Acceptance Criteria

| Criterion | Result | Evidence / boundary |
|---|---|---|
| AC1 Multi-quarter database | PASS | 26 consecutive quarters |
| AC2 Source provenance | PASS | All 692 facts link to hashed official documents |
| AC3 Forecasts not overwritten | PASS | Two snapshots plus database UPDATE/DELETE rejection tests |
| AC4 Historical known-information reconstruction | PARTIAL | Working as-of CLI and 2023-05-25 example; conservative bounds, exact intraday completeness not proven |
| AC5 No future filing exposure | PASS (engine) | Availability filters and later-filing/revision tests; archival source-vintage limitation remains |
| AC6 Quarter/YTD separation | PASS | Explicit duration logic, same-filing YTD tests, Q4 differencing, no EPS subtraction |
| AC7 Deterministic features | PASS | 546 persisted versioned features, deterministic re-execution tests |
| AC8 Idempotent ingestion | PASS | Actual cached-source rerun 0 new / 692 skipped; SEC mocked rerun also passes |
| AC9 Tests | PASS | 49 tests, 0 warnings/failures; Ruff and mypy clean |
| AC10 Latest official-source validation | PASS | 18 numeric checks against NVIDIA release; not a completed SEC cross-check |
| AC11 Labels isolated from features | PASS | Separate DB; selecting future_outcomes from feature DB fails |
| AC12 No invented reported values | PASS | Official-source observations only; synthetic fixtures confined to tests |

M1 is delivered for PM review, **not declared fully accepted**. AC4 and the listed live-data gaps remain open.

## Next Recommended Milestone

After PM review, perform a focused PIT data-acceptance milestone: configure the SEC identity, ingest/reconcile SEC originals, establish exact event timestamps and split/share/price bases, and close the structured-guidance gaps. Continue to defer trading thresholds and AI valuation decisions. No work beyond Milestone 1 has been started.
