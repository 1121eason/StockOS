# Point-in-time semantics and limits

## M1.1 authoritative availability and basis

Use `PointInTimeRepository`, not raw legacy fact timestamps. `availability_evidence` records independent proof for each document/content scope. The repository resolves verified minute/exact evidence before filtering; source facts and prior snapshots remain immutable. Minute timestamps use a conservative end-of-minute bound. Current coverage is 26 verified minute-level financial and guidance disclosures, while IR website times remain date-only and live SEC times are absent.

`PriceBasis` separates as-traded reconstruction, split-only comparisons and vendor dividend-adjusted close. The opening observation is visible at the regular open; HLC require the bar close. Historical valuation aligns all per-share inputs to the price's trading denomination, rejects unknown share bases, and never replaces period-end shares with weighted averages. Source retrieval times remain visible and current-vintage price reconstruction is explicitly labeled. Forward replays are not historical observed forecasts.

## Times

Every persisted timestamp is timezone-aware UTC (`TIMESTAMP WITH TIME ZONE` in PostgreSQL; a rejecting/converting SQLAlchemy type for SQLite). CLI financial timestamps display `America/New_York`. Economic period dates are dates, not timestamp substitutes.

- `period_end`: economic end of the reported interval/balance.
- `filing_date`: SEC filing calendar date; never midnight publication by assumption.
- `accepted_timestamp`: SEC acceptance with explicit timezone (naive SEC headers interpreted as ET).
- `earnings_release_timestamp`: exact release instant if reliable; NULL in the initial IR dataset.
- `reported_at`: exact publication proxy or documented date-only upper bound.
- `available_at`: operational `information_available_at`. For current IR data this is an explicitly conservative **upper bound**, not the exact first public instant.
- `tradable_at`: first regular-session open at or after `available_at`.
- `retrieved_at` / `created_at`: when this system observed/stored the source/result; never substitutes for historical financial publication.

Date-only announcements become usable at 00:00 ET the following day. Thus a normal after-hours release remains available for the next morning but the system intentionally under-represents information already known during the release evening. This prevents false precision; this remains the fallback when independent minute-level evidence is unavailable.

SEC API acceptance receives a 3-minute conservative dissemination buffer. SEC describes typical availability lags, not a guarantee; exact historical dissemination is not proven. Missing acceptance falls back to the next midnight after filing date. Metadata records the policy.

The trade function always waits for a session **open**, including an intraday announcement. It never buys retrospectively at that day's close. Weekends, holidays, early closes and DST come from the exchange calendar.

## Facts and restatements

The repository first filters `available_at <= cutoff`, then chooses a metric vintage. `originally_reported` chooses the earliest eligible report, breaking simultaneous ties by explicit source priority. `latest_restated` chooses the latest eligible report. A later report cannot be seen in an earlier query. Simultaneous equal-priority conflicting values yield unavailable rather than arbitrary selection.

`is_restated` means a changed later value is a **revision candidate**, not a verified accounting restatement. It may reflect a split or taxonomy presentation. The source-disagreement issue retains both values for investigation.

Current companyfacts data are sliced by accession and attached to that filing's availability; later-accession comparisons do not get the original period's timestamp. If an already-seen accession extract or release body changes, its new facts become available at retrieval, never silently backdated. An initially fetched historical web page/API cannot prove that the provider never edited it before first retrieval; independently archived vintages remain future validation work.

## Quarter/YTD conversion

- Quarter-duration amounts are kept directly.
- Cash flows/other additive metrics: current YTD minus prior YTD with same fiscal start, concept and unit, available by the same cutoff. Prefer both operands from the same accession. Otherwise mark mixed-vintage arithmetic.
- Q4: annual minus nine-month total, if a directly reported quarter is absent.
- EPS, weighted-average shares and margins are **never subtracted** as additive flows.
- Every derivation retains all input fact IDs and availability is the maximum of its inputs.
- SEC `fy/fp` describes the filing, so economic periods are derived separately from period dates.

## Forecast vintage

An old cutoff does not make a forecast historically real. Reconstructed forecasts are `historical_replay`; forward P/E requires `generated_kind=live`, `forecast_as_of <= cutoff`, **and** `created_at <= cutoff`. It also requires an explicitly annual forecast; next-quarter EPS is not multiplied by four and mislabeled FY1/FY2.

## Prices and labels

Daily `timestamp` is session open and `available_at` is bar close; the full OHLC bar is unavailable at its opening. Current-vintage split-adjusted Yahoo OHLC cannot be combined with original pre-split EPS/shares. Historical valuation excludes these bars. Genuine unadjusted prices also require observed retrieval by the historical cutoff.

Outcome labels use first tradable open, session-end closes and calendar-month horizons, with not-yet-matured horizons NULL. The label dataset is retrospective and never a feature input. Returns are split-adjusted **price** returns, excluding dividends. Drawdown/upside use daily closes, not intraday extrema.

EPS growth across known 2021/2024 split discontinuities is withheld, rather than generating false collapses. Full split-vintage reconstruction is a known gap.


## Exact decimal storage

Revision `0003_exact_decimals` stores canonical decimal text on SQLite and native NUMERIC on PostgreSQL. Both return Decimal and apply the declared scale with half-even rounding. Financial arithmetic uses the Python calculation layer, not SQLite CAST/arithmetic over text. The online migration validates every copied record and foreign key, restores immutable-row guards, and retains pre-migration backups. It preserves legacy numeric approximations; new writes avoid binary storage loss. A lossy downgrade is intentionally unsupported; restore a saved database backup when rollback is required.
