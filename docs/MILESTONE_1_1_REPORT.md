# Milestone 1.1 — Point-in-Time & Market Data Hardening

Status: **PARTIAL — not accepted for walk-forward valuation/backtest use.** Milestone 2 remains stopped.

## Completed

Implemented an append-only evidence layer, migrations `0002_hardening` and `0003_exact_decimals`, formal corporate actions, separated price bases, SEC identity configuration, primary filing capture, SEC/IR reconciliation, timestamp-aware financial/guidance queries, split-normalized historical P/E, guidance coverage, and quality reviews. Original M1 facts and snapshots remain preserved. Intermediate development databases are retained separately; final SQLite data was rebuilt by upgrading the preserved M1 baseline and replaying the verified sources.

Current research database: 26 quarters, 713 financial facts, 55 source documents, 1,682 original vendor bars and 1,682 price-basis records. The source bytes are hashed and retained. No AI, valuation calibration, scoring, trading signals or strategy optimization was started.

## SEC Coverage

**Actual SEC filings: 0. Actual SEC facts: 0.** No contact identity has been supplied. `qve configure-sec` prompts for project/email, validates the value, preserves other environment settings and writes `.env` with owner-only permissions. It does not require an SEC account or API key. The supplied contact is sent to SEC in the HTTP User-Agent header; it is not committed or printed in ingestion logs.

The adapter downloads submissions/history, companyfacts, accession extracts and primary 10-Q/10-K HTML. Accessions have a database uniqueness constraint. Synthetic HTTP integration tests exercise ingestion, archive capture, repeat ingestion and primary-document uniqueness. These are **not evidence of successful live SEC downloads**.

Reconciliation retains both facts and records match/conflict/unknown-basis results. Canonical selection remains cutoff-aware: earliest eligible information for `originally_reported`; SEC concept priority breaks simultaneous ties only. `latest_restated` is an explicit alternative. Equal-priority simultaneous conflicts return missing rather than a guessed value. SEC per-share contexts without a verified basis are rejected by valuation. Real SEC/IR reconciliation and actual SEC repeat-ingestion acceptance remain pending.

Evidence: `data/m11/report/sec-coverage.json`; `tests/integration/test_sec.py`; `hardening/reconcile.py`.

## Timestamp Coverage

| Timestamp class | Exact | Minute | Date only | Inferred | Unresolved |
|---|---:|---:|---:|---:|---:|
| Issuer-distributed earnings financial content | 0 | 26 | 0 | 0 | 0 |
| NVIDIA IR website's own publication time | 0 | 0 | 26 | 0 | 26 intraday times |
| Target-quarter SEC accepted timestamp | 0 | 0 | 0 | 0 | 26 |

These rows describe different clocks, not a combined total. A known IR date still has an unresolved intraday time. The earnings row means the independently verified distribution time, not a claim about the IR website's clock. The IR website dates remain known, while its intraday times remain unknown.

All 26 releases have matching parsed financial values in the timestamped Nasdaq/GlobeNewswire distribution. Guidance and segment evidence are independently compared before applying the timestamp to those scopes. All 26 guidance scopes also matched. `timestamp_precision`, source, confidence, fallback reason and timezone remain explicit.

Visible publication times are kept at **minute** precision, even when a distribution HTML attribute includes seconds. The information boundary is the **end of the stated minute**. Most sources state 16:20 ET; [FY2026 Q4 states 16:31 ET](https://www.globenewswire.com/news-release/2026/02/25/3245078/0/en/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2026.html), yielding a conservative 16:32 ET boundary. This is a bound, not a claimed exact dissemination instant.

Original date-only facts are not rewritten. The PIT repository resolves their effective availability through append-only evidence; raw legacy `financial_facts.available_at` is not the authoritative M1.1 query interface. Unknown times retain next-midnight ET fallback. SEC-only disclosures never inherit an IR timestamp. SEC acceptance plus three minutes is explicitly a dissemination proxy, not verified publication; the SEC describes typical processing delays, not a guaranteed maximum. [SEC access FAQ](https://www.sec.gov/about/webmaster-frequently-asked-questions).

Evidence: `timestamp-coverage.json`, `timestamp-verification.json`, 156 stored scope assertions including retained fallbacks.

## Corporate Actions / Split Validation

Both splits affecting the target historical period are modeled:

| First split-basis trading date | Distribution/effective date | Share multiplier | Evidence |
|---|---|---:|---|
| 2021-07-20 | 2021-07-19 | 4 | [NVIDIA announcement](https://nvidianews.nvidia.com/news/nvidia-announces-four-for-one-stock-split-pending-stockholder-approval-at-annual-meeting-set-for-june-3) |
| 2024-06-10 | 2024-06-07 | 10 | [NVIDIA final split FAQ](https://investor.nvidia.com/files/doc_downloads/2024/06/nvidia-2024-stock-split_faq_investors.pdf) |

This is target-period coverage, **not a claim that all pre-2020 corporate actions were imported**. Original release EPS and diluted weighted shares use the release's presentation basis. Known factors multiply shares and divide EPS/prices. Unknown SEC share bases remain unavailable for valuation.

All 26 quarters pass EPS/weighted-shares/price basis checks; EPS × weighted shares also reconciles to reported net income within the explicitly calculated rounding tolerance. Period-end shares remain absent. Synthetic regressions verify the combined 40-fold adjustment and P/E/market-cap invariance through a split.

## Market Price Basis

The original Yahoo OHLC are split-adjusted current-vintage values. The original JSON response is now retained; all 1,682 bars match its OHLC within the stored eight-decimal precision. Its split events agree with the official corporate-action model.

The database distinguishes provider bars, split-only comparable OHLC, provider adjusted close, total adjustment factor and reconstructed as-traded OHLC. Adjusted open/high/low stay NULL because the provider did not supply them. Every basis row references the vendor bar, archived response hash, retrieval time and corporate actions used.

**1,682 reconstructed as-traded bars; 0 independently supplied raw/as-traded bars.** Reconstruction multiplies split-adjusted OHLC by subsequent split factors. It preserves vendor rounding noise and is labeled `research_reconstructed`; it is never represented as a contemporaneously observed raw-price archive. `get_price_as_reported(require_observed=True)` rejects these rows. A separately verified raw-price provider remains an open requirement for stronger price acceptance.

`get_price_as_reported()` and `get_split_adjusted_price()` return explicit basis/provenance. The engine uses as-traded valuation-date denominations. Daily HLC cannot be used at the open. A new financial release cannot be valued using a close preceding its first permitted regular-session execution time. The execution policy waits for the next regular open even for intraday releases; this conservative choice is tested and documented.

## Historical Valuation Availability

| Metric | Available quarters | Limitation |
|---|---:|---|
| Trailing P/E | 23/26 | Research reconstruction; first three quarters lack a full four-quarter window |
| Market cap | 0/26 | No verified period-end shares |
| FCF yield | 0/26 | No market cap |
| Enterprise value | 0/26 | No market cap; some cash/debt disclosures also remain absent |
| FY1/FY2 forward P/E | 0/26 | No valid observed annual forecast with verified share basis |

`historical_replay` is equivalent to `research_reconstructed_forecast`; it is excluded from historically observed estimates. A stored `live` forecast must also satisfy its creation/as-of cutoffs. Existing next-quarter baseline forecasts are not annual estimates.

The three actual archive regressions give the following first-open examples (display rounded; source values and formulas retained):

| Quarter | Reconstructed opening price | Normalized TTM EPS | Trailing P/E | Full PM gate |
|---|---:|---:|---:|---|
| FY2022 Q1 | $627.99 | $8.45 | 74.32 | FAIL: market cap missing |
| FY2024 Q1 | $385.23 | $1.92 | 200.64 | FAIL: market cap missing |
| FY2027 Q2 | $222.86 | $7.91 | 28.17 | FAIL: market cap missing |

All three pass before/after visibility, first-open price alignment and trailing P/E checks. None is a complete PM pass. Evidence: `pm-gate.json`, `historical-valuations.json`, `quarterly-basis-validation.json`.

## Guidance Coverage

**104/104 quarter × metric cells structured**: 26 quarters × Revenue, GAAP Gross Margin, GAAP Operating Expenses and tax guidance. Current matrix counts: structured 104, text-only 0, unavailable 0, ambiguous 0.

The deterministic parser now accepts early “percent” wording, older outlook headings, dollar/space punctuation, GAAP-only expenses, and distinct GAAP/non-GAAP tax rates without treating the latter as a numeric range. Full-year tax guidance remains annual; annual expense discussion no longer incorrectly makes subsequent quarterly tax guidance annual.

There are 108 retained guidance records because four older interpretations remain immutable. The current coverage and forecast input selection use the verified current parser interpretation (104 cells). Raw release bytes and original outlook text remain available; no LLM filled values. Evidence: `guidance-coverage.json`.

## PostgreSQL Validation

Actual local **PostgreSQL 17.10**, isolated container `stockos-m11-postgres`, loopback port 55439. The final core validation database is `qve_verified`; `qve` retains earlier development runs. Core and separate label migrations were applied through `0003_exact_decimals` / `0002_labels_exact`. Actual cached issuer ingestion created 713 facts; all 1,682 real vendor bars were replayed. PIT queries, 26 first-open snapshots, 546 features and historical ratio outputs were executed. Repeat ingestion created zero facts and the full workflow's second-run table counts were unchanged.

The full 76-test suite passed on PostgreSQL, including the live applied-migration contract and the three actual archived NVIDIA regressions. The one discovered backend-specific test failure was an assertion that recognized only SQLite's missing-table error wording; both databases correctly reject access to the separate future-outcomes table. The assertion now checks the supported error messages.

This validates the live PostgreSQL engine and cached real issuer workflow. It does not turn mocked SEC responses into live SEC coverage. PostgreSQL uses native NUMERIC. SQLite now stores canonical decimal text and returns Python Decimal, preventing binary floating-point loss. Both backends use the same declared scale and half-even rounding. New regressions verify 30-digit amounts and rounding boundaries. All 546 current feature values were compared between SQLite and PostgreSQL and match exactly at the declared precision. The storage migration preserved all existing values, IDs and immutable-row guards; 13 table audits have matching before/after semantic hashes (including 26 isolated outcome labels). Previously stored legacy approximations are preserved honestly rather than silently rewritten. Financial arithmetic goes through Python Decimal; direct SQLite numeric SQL over the decimal-text columns is outside the supported calculation interface.

Both PostgreSQL dump artifacts were restored into newly created temporary databases. Every restored table's row count and semantic hash, plus all user trigger definitions, matched its source database. The temporary databases were removed afterward. Evidence: `data/m11/postgresql/dump-restore-validation.json`.

Evidence: `data/m11/postgresql/validation.json`, `latest-test-validation.json`, `test-results.txt`, `data/m11/decimal-migration-audit.json`, source/coverage reports and PostgreSQL dump artifacts.

## Test Results

- SQLite: **75 passed, 1 skipped**. The skipped check explicitly requires the live PostgreSQL database.
- PostgreSQL: **76 passed**.
- Ruff lint/format and mypy passed.
- Actual full workflow replay is idempotent by table counts; source hashes verified 55/55.
- The unit/integration suite is green; **PM end-to-end acceptance remains failed** because the real market-cap outputs are missing. These are different conclusions.

New coverage includes scoped timestamp evidence, exact/minute distinction, release boundaries, premarket/intraday/after-hours/weekends/holidays/early closes/DST, two-split normalization, price field visibility, adjusted/raw separation, split-invariant P/E, SEC primary-document idempotency, SEC/IR conflict preservation, and live PostgreSQL migrations.

Portable archive reads retain original source paths and fall back to the configured hash archive when the original files are absent. All 55 documents were independently read through this relocation path, with hash verification. Regression tests reject altered source bytes. Source and data archives have separate per-file hash manifests and exclude credentials, runtime caches and development databases.

## Remaining Data Quality Issues

All original **142** issues were reviewed without deletion: **43 blocking / 99 non-blocking**, including resolved issues retained with evidence. Five new issues document the price-source limitation, absence of observed annual forecasts and the three incomplete initial TTM windows.

Current total: **147 reviews, 44 blocking / 103 non-blocking**.

| Classification | Count | Meaning |
|---|---:|---|
| Timestamp Gap | 26 | Resolved with minute evidence; original issues retained |
| Parser Defect | 50 | 42 cash/securities observations plus 8 guidance gaps resolved with evidence |
| Source Limitation | 44 | 26 period-end-share gaps; 3 cash and 3 securities gaps; 5 current-debt and 5 total-debt gaps; SEC identity; independent raw-price source |
| Definition Difference | 23 | Engine FCF vs issuer FCF equipment-payment treatment; both definitions retained |
| Expected Missing | 4 | Three incomplete initial TTM windows and no observed annual forecasts |
| Reconciliation Conflict | 0 actual pairs | SEC ingestion absent; mechanism tested, not a clean live reconciliation claim |

The remaining cash gaps involve restricted-cash presentation; restricted cash is not silently substituted for cash equivalents. Missing current debt is not assumed to be zero. Weighted-average diluted shares are never substituted for period-end shares.

Evidence: `quality-review.json`, including original issue IDs, classifications, blocking status, resolution and supporting observations.

## Acceptance Criteria

| Criterion | Result | Evidence / unresolved condition |
|---|---|---|
| AC1.1 Actual SEC ingestion | **FAIL** | 0; needs user-supplied contact identity |
| AC1.2 Actual SEC idempotency | **FAIL** | Not executed online; synthetic test passes |
| AC1.3 SEC/IR reconciliation | **PARTIAL** | Mechanism and tests complete; no actual SEC pairs |
| AC1.4 Information availability | **PASS** | 26 minute-level issuer distributions; date-only/SEC gaps explicitly labeled |
| AC1.5 Tradable timestamp | **PASS** | Calendar and timing regressions pass |
| AC1.6 Split model | **PASS** | Both splits in the target period modeled and verified |
| AC1.7 Raw/adjusted price separation | **PARTIAL** | Architecture and reconstruction complete; independent raw provider absent |
| AC1.8 Consistent historical P/E basis | **PASS** | Explicit source bases, 26 quarterly checks and split-invariance regressions |
| AC1.9 Historical valuation availability | **PARTIAL** | 23 reconstructed trailing P/E; market cap/EV/FCF yield absent |
| AC1.10 Guidance matrix | **PASS** | 104 structured cells, traceable source/interpretation |
| AC1.11 PostgreSQL workflow | **PASS** | Actual migrations, issuer ingestion, PIT/features and 76 tests |
| AC1.12 Three complete PM gates | **FAIL** | All three still lack market cap |

## PM Decision Required

No approval to start Milestone 2 is requested. First supply the SEC contact identity and complete the missing real-data validation. If stronger raw-price acceptance requires a separate vendor, select an available raw-price source/account; no paid service was purchased or configured. Reconstructed prices remain visibly labeled and are not being offered as a silent relaxation of the acceptance criteria.

The implementation is delivered as partial M1.1 work with reproducible evidence. Continue M1.1 after the missing inputs are available; do not start M2.
