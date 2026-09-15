# ValuationPolicyV2 — deterministic forward valuation research

## Inputs and ratios

Use the accepted M1.1 first permitted regular-session opening price, eligible PIT shares outstanding, and eligible cash/debt. Forward estimates come from the immutable **first-tradable** internal GAAP ForecastPolicyV1 run. NTM is four future quarters. FY1/FY2 follow the explicit fiscal-roll definition in FORECAST_METHOD.md. NTM EPS is aggregate net income / calendar-day-weighted diluted shares on the valuation-date basis, so both price and EPS have consistent units.

NTM/FY1/FY2 P/E = price / positive corresponding forecast EPS. Forward FCF Yield = NTM engine FCF / positive PIT market cap, retaining negative FCF where present. Forward EV/EBIT requires valid EV and positive NTM operating income. No today-known EPS is substituted into an old forecast.

Historical context uses only observations strictly earlier than the current timestamp, same model version and assumption hash, one observation per historical checkpoint. For NTM P/E, trailing P/E, trailing FCF yield, forward FCF yield and forward EV/EBIT report expanding median, P25, P75, midrank percentile, population z-score and sample count. Minimum four prior values; a zero dispersion leaves z-score unavailable. Today's observation is excluded from its reference distribution. No fair or target multiple is inferred from the distribution.

## DCFPolicyV1 cash-flow compatibility

This is enterprise DCF using an explicit **NOPAT cash-conversion FCFF proxy**, not an assertion that reported CFO − CapEx is unlevered FCFF:

`FCFF proxy = operating income × (1 − tax rate) + (forecast OCF − forecast net income) − forecast CapEx`.

Equivalently, replace net income in the engine FCF with after-tax operating income. This removes forecast net nonoperating income rather than discounting an interest-bearing equity cash-flow measure at WACC. Operating cash conversion still approximates noncash charges, working capital and cash classification. SBC is not charged twice. The proxy does not claim to be a detailed tax-shield or cash-interest schedule.

Matching firm cash flows with cost of capital and equity cash flows with cost of equity follows [Damodaran's primary valuation material](https://people.stern.nyu.edu/adamodar/New_Home_Page/problems/dcfprob.htm). The operating-cash-flow construction is also explained in his [cash-flow definitions](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/littlebook/cashflows.htm). Our explicit approximation and constants are research-policy choices, not figures supplied by those sources.

Years 1 and 2 are the next eight quarters grouped into consecutive four-quarter windows, avoiding partial-fiscal-year discount timing. Years 3–5 extend the second year's growth, bounded [-50%, 100%], then decay halfway toward the base 2.5% terminal growth each year. Bounding events are saved. At least two positive complete forward FCFF years are required for this extension; otherwise DCF is unavailable.

Enterprise value = the five end-of-year discounted FCFFs + discounted Gordon terminal value. Equity value = enterprise value + eligible cash − eligible debt. Divide by **PIT shares outstanding**, never forecast diluted weighted shares. Negative modeled equity values are retained and flagged. Missing debt is not zero. Carried historical balances retain their dates and sources.

## Assumptions and sensitivity

DCFPolicyV1 assumes a research WACC grid of 8%, 9%, 10%, 11%, 12% and terminal-growth grid of 2%, 2.5%, 3%. The base is 10%/2.5%. These are versioned scenario assumptions, not an estimated uniquely correct NVIDIA WACC and not chosen using future prices or returns. Each of 15 cells has its inputs and value persisted. Explicit Year 3–5 forecasts stay fixed at the base extension policy across the grid; terminal-growth columns change the terminal formula only.

DCF low/high are min/max sensitivity values, **not probabilistic confidence limits**. There is no target P/E, calibrated trading threshold or Buy/Hold/Sell output.

## ReverseDCFPolicyV1

Starting cash flow is the eligible trailing four-quarter FCFF proxy on the same economic definition. Solve for a constant five-year FCFF CAGR that makes enterprise DCF equal the observed PIT enterprise value. Use Decimal bisection within [-90%, 200%], maximum 200 iterations, requiring relative EV residual ≤ 1e-10. Require finite positive EV and starting FCFF, valid WACC > terminal growth, and a bracketed root. Return an explicit failure reason otherwise; no extrapolation.

Internal 5Y CAGR = (Year-5 forecast FCFF / trailing starting FCFF)^(1/5) − 1. Expectations Gap subtracts reverse implied CAGR from this internal CAGR. Both use the same starting FCFF, five-year timing, WACC and terminal assumptions. This is a comparison of research expectations, not a price prediction or instruction to trade.

## Versioning and provenance

M2 stores `research_valuations` and `dcf_scenarios`, linked to existing immutable M1.1 valuation rows and new forecast runs. M1 historical snapshots are not overwritten. Every output carries model version, assumption ID, price/source basis, financial input IDs, and share availability. Historical runs are research reconstructed. Evaluation labels are separate from forecast inputs. Sparse data, rapidly changing economics, one-time charges, balance carry-forward, simple cash conversion and empirical-error instability remain explicit limitations.
