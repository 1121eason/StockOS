# Backtest temporal audit

## Status and scope

`WalkForwardBacktester` produces a **reconstruction diagnostic**, not a verified
point-in-time backtest or historical out-of-sample result. This change corrects
execution timing conditional on the supplied availability contract. It does not
establish that reconstructed signals or their inputs existed historically.

Timing version: `nasdaq_next_regular_open_v2`.

The earlier, unversioned implementation is referred to here as
`date_on_or_after_v1`: it chose the first price bar with `date >= as_of_date`, even
though its own comment described the signal as known after market close. That
allowed an after-close signal to trade at the same date's earlier open. The old
implementation also silently skipped signals without a later bar and silently
overwrote signals mapped to the same execution bar.

This patch changes execution, validation, and diagnostic reporting. It does not
change strategy thresholds, fit parameters, optimize allocations, import actual
market data, validate original vintages, or regenerate historical results.

## Per-quarter input contract

Every `panel_quarters` entry must include `as_of_date` as a canonical `YYYY-MM-DD`
NASDAQ-local calendar date.

An entry may also include `signal_available_at` as an ISO timestamp containing
`T` and a timezone offset or `Z`, for example:

```json
{
  "quarter": "Q1",
  "as_of_date": "2024-01-03",
  "signal_available_at": "2024-01-03T20:00:00-05:00"
}
```

This field asserts when the **complete decision signal**, including all inputs
used to derive it, became available. It is a source assertion, not a verified
publication timestamp. A filing's publication time alone is insufficient if the
model or another required input became available later. Callers must not invent
an earlier timestamp to obtain a same-session fill. Supplied availability cannot
precede `as_of_date` when converted to America/New_York.

When `signal_available_at` is absent, the scheduling boundary is midnight at the
start of the following America/New_York calendar date. This waits until the
entire `as_of_date` has elapsed, including on early-close sessions. It does not
assume a 16:00 release or claim that publication really happened at midnight.
The report leaves `signal_available_at` null and labels the separate
`scheduling_available_at` as `date_only_conservative_boundary`.

A present but malformed, null, or timezone-naive `signal_available_at` raises an
error. It never silently falls back to the date-only rule. This fallback is
conservative relative to same-date execution; it does not prove the complete
signal was actually available by the next session.

## Calendar and execution rule

The existing `valuation_engine.time` NASDAQ `sessions`, `ET`, and
`calculate_next_tradable_timestamp` utilities determine the first regular-session
**open at or after** the asserted availability or conservative scheduling
boundary. UTC comparisons are handled by the existing calendar utility.

Examples, using synthetic dates:

- January 3, 2024 at 09:00 ET: January 3 at 09:30 ET.
- Exactly 09:30 ET: that session's open, under the zero-latency execution assumption.
- January 3 at 09:30:00.000001, intraday, or after close: January 4 at 09:30 ET.
- Date-only January 3: January 4 at 09:30 ET.
- Friday January 12: Tuesday January 16, after the MLK holiday.
- July 3, an early-close date, or July 4, a holiday: July 5 at 09:30 ET.
- DST transitions use the exchange's actual local/UTC open, not a fixed UTC hour.

Execution eligibility is determined **before examining which prices happen to
be present**. The exact first eligible session's bar must exist. A missing bar
fails the entire run, even when a later bar exists or the signal falls beyond
the price horizon. There is no forward fill, next-available-bar substitution,
or silently omitted final signal.

The simulated window and passive/cash benchmarks all begin at the first eligible
execution open. Earlier supplied bars are excluded; there is no phantom initial
quarter, pre-signal strategy return, or earlier benchmark entry.

## Fail-closed validation

Before policy evaluation and simulation:

- Parse all date and availability fields.
- Sort signals by `as_of_date` and then availability, independent of manifest
  object insertion order.
- Require availability to increase with that order.
- Reject collisions or reversals in execution order instead of overwriting one
  signal with another.
- Require supplied bar dates to be canonical, unique, strictly increasing, and
  actual NASDAQ regular sessions. Do not sort or deduplicate broken price data.
- Require finite, positive numeric open and close prices.
- Require the first calendar-eligible bar for every signal.

These checks do not establish complete historical price coverage. Nonexecution
session gaps between supplied bars remain outside this patch's scope. Existing
cash accrual and performance annualization use one step per supplied bar and
252 steps per year. Thus sparse synthetic fixtures are useful for invariants,
but their annualized metrics must not be interpreted as historical performance.

## Report contract and remaining limitations

Every constructed `BacktestReport` includes non-constructor-overridable defaults:

- `classification = "reconstruction_diagnostic"`
- `historical_oos = false`
- `timing_version = "nasdaq_next_regular_open_v2"`
- `source_vintages_verified = false`
- `model_vintages_verified = false`
- `price_vintages_verified = false`
- Explicit limitations about unverified assertions, date-only boundaries,
  noncomparability, and execution assumptions.

`execution_schedule` records each quarter's original date, optional asserted
availability, scheduling boundary and basis, exact execution timestamp/date,
NASDAQ calendar, and `availability_verified = false`. These fields survive
`dataclasses.asdict` serialization. Manifest fields claiming OOS or vintage
verification cannot promote the report to a stronger evidence class.

The timing fix cannot establish original source/document vintages, historical
model snapshots or training cutoffs, historical feature availability, unchanged
policy selection, price/corporate-action vintages, or consistent adjusted OHLC.
It also does not model real publication/processing latency, opening-auction
participation, intraday fills, spreads, or market impact. A source timestamp
assertion alone does not close those gaps.

Results under this version are **not comparable** with prior diagnostic results
using the same-date rule. Historical results must not be relabeled as validated
PIT/OOS, spliced into the new curve, or used to claim alpha from this correction.
Existing overnight holdings, gap valuation, fee, turnover, cash, and policy
accounting rules are preserved.

## Verification

Focused synthetic coverage includes:

- Date-only next-session behavior, weekends, holidays, early closes, and both
  DST transitions.
- Explicit pre-open, exactly-open, immediately-after-open, intraday, and
  after-close timestamps; UTC and other offsets; no execution before availability.
- A large synthetic overnight gap proving an after-close signal cannot capture
  the preceding open or that gap.
- Malformed/naive timestamps and malformed dates; missing first-eligible and
  final-signal bars; collisions and conflicting signal order.
- Unordered, duplicate, non-session, malformed, and invalid-price bars.
- Report classification/vintage limitations and preservation through serialization.
- Existing allocation thresholds and strengthened overnight NAV/fee invariants.

Commands run from the repository using the shared Python environment:

```text
python -m pytest tests/unit/test_backtest_temporal.py tests/unit/test_walk_forward_backtest.py tests/unit/test_p0_governance_and_ablation.py -q
mypy src/valuation_engine/backtest/walk_forward.py tests/unit/test_backtest_temporal.py tests/unit/test_walk_forward_backtest.py tests/unit/test_p0_governance_and_ablation.py
ruff check tests/unit/test_backtest_temporal.py
ruff format --check tests/unit/test_backtest_temporal.py
```

The focused tests pass with the pre-existing real-data integration test skipped
because its local database/manifest are absent. No historical-data backtest was
run. Focused mypy and new-test lint/format checks pass. Ruff on the three legacy
files still reports pre-existing import/style/type-alias warnings; no mass
formatting or unrelated cleanup was applied.
