# ForecastPolicyV1 — NVIDIA deterministic GAAP research

Status: fixed methodology selected before the full 26-quarter accuracy evaluation. The model is not fit to stock returns. All constants are in `src/valuation_engine/research/policy_v1.json`, persisted as immutable `forecast_assumptions` with the assumption content hash. The policy was created in September 2026; applying it to earlier data is **research_reconstructed_internal**, never a claim that these forecasts or coefficients existed historically.

## Boundary and ownership

M1.1 PIT, issuer end-of-minute, SEC acceptance proxy, original-vintage selection, split normalization, and shares contracts remain unchanged. M2 adds tables and reads the accepted repository. Issuer-release and first-tradable forecasts are separately timestamped. The latter is the primary valuation checkpoint. Forecasts at other explicitly requested cutoffs are classified `research_replay`; historical valuation commands require the exact first-tradable timestamp.

Only eligible financial facts, GAAP guidance, prior immutable internal forecasts, and already realized financial facts can enter forecasting. No price, return, valuation, evaluation-label or Future Outcomes table is read by the forecast calculation. Calibration recomputes errors from prior internal projections plus then-known financial results; it never imports the evaluation package or opens the label database. Prices are introduced only in the later valuation step. Research labels live in the separate label database.

## Financial model

The income statement is calculated in this order: Revenue × Gross Margin = Gross Profit; subtract GAAP OpEx; add forecast nonoperating income; apply the tax policy; divide net income by forecast diluted weighted-average shares. All arithmetic uses Decimal, and stored numeric results have eight decimal places. Negative or zero P/E denominators produce unavailable P/E.

Model A is the primary Guidance Anchored Baseline. Q+1 revenue, gross margin and GAAP operating expenses begin with current eligible guidance. The raw low/mid/high, source and adjusted midpoint are retained. Revenue and OpEx bias use median relative surprise; GM bias uses median ratio difference (percentage-point interpretation). Use up to eight unique already-realized target quarters, minimum four; below four the adjustment is exactly zero and labeled insufficient_history. Relative adjustments are bounded at ±25%, GM at ±5 percentage points, with every bound event recorded.

Beyond Q+1, combine the median of four recent YoY growth rates and annualized median sequential growth with equal weights, plus one-quarter acceleration at a 0.25 weight. Annual growth is bounded to [-75%, 200%]. Sequential growth is bounded to [-50%, 75%] before annualizing. Each successive quarter reverts toward 8% long-run growth with 0.85 persistence. Fiscal seasonality is the median same-quarter sequential ratio divided by the recent overall sequential ratio, bounded to [0.8, 1.2]. Use the preceding forecast revenue as the anchor. Missing growth history uses a disclosed zero sequential trend and seasonality one, not a generated financial fact.

Model B applies the same transparent historical trend and financial model but does not use Q+1 revenue/GM/OpEx guidance to anchor its path. Both use the common eligible management tax guidance where valid. Model C blends A and B revenues, gross profits and OpEx at fixed 50/50 weights, then recomputes the income statement; it does not average P/E ratios or directly guess EPS. These weights are not optimized after observing accuracy.

Gross margin reverts from the Q+1 anchor to the recent four-quarter median with 0.75 persistence and a decaying 0.25 recent-margin-change term. Q+1 guidance itself is used without the beyond-Q+1 trend term. Hard domain is [0, 1]; company warnings are outside [0.30, 0.85]. All point-forecast clipping is recorded. OpEx is independently audited: its latest amount or Q+1 GAAP guide grows by median historical sequential OpEx growth, bounded [-25%, 50%], decaying with 0.85 persistence. It is not inferred from a desired EPS or stock price.

Tax uses valid management guidance first, otherwise the median of up to four eligible effective tax rates with positive pretax income and rates between 0% and 35%. Missing or abnormal observations are excluded with warnings. No valid rate means unavailable net income/EPS. A forecast loss is assigned no tax benefit, explicitly recorded by the policy flag and a warning. A current tax guide is held constant across the projection horizon as an approximation.

The EPS denominator is **forecast diluted weighted-average shares**, a distinct semantic type from PIT market-cap shares. Normalize historical diluted shares to the forecast-cutoff share basis, then use median recent sequential share change, bounded ±5%, decaying at 0.85. Fewer than two comparable changes uses a documented flat baseline. Future share observations and unannounced splits are excluded. All future projections remain on the forecast-cutoff comparable basis; later evaluation converts both sides to the same basis.

## Cash flow

`FCFMarginCashConversionV1` preserves canonical engine FCF = OCF − reported CapEx. It combines two transparent estimates at fixed 50/50 weights: forecast revenue × median recent FCF margin, and forecast net income + forecast revenue × median[(actual OCF − actual net income)/actual revenue] − projected CapEx. CapEx uses the recent median CapEx/revenue. If only one estimate is supported, the available baseline is used with its method recorded. Forecast OCF is FCF + CapEx.

The cash-conversion term contains historical working-capital and noncash effects. Current AR/revenue or inventory/revenue exceeding 1.5 times its preceding recent median generates a warning; the model does not pretend it can precisely predict collections, inventory write-offs or payables. FCF margins outside ±100% are flagged, not silently clipped. Negative FCF is retained. SBC treatment follows the disclosed OCF baseline; dilution trend is modeled separately. Issuer FCF definitions remain separate in M1.1.

## Horizons, revisions and intervals

Produce eight future fiscal quarters. NTM is the next four fiscal quarters and is the primary forward denominator. FY1 is the current fiscal year until Q4 becomes known, then the next fiscal year; FY2 follows FY1. FY1 combines known actual quarters and forecast remaining quarters. Aggregates sum financial flows and use calendar-day-weighted quarterly diluted shares. Aggregate EPS is aggregate net income divided by that denominator; this is a consistent reconstructed annual measure, not a claim to replicate a subsequently published annual EPS rounding convention. Missing required components remain NULL.

Revisions compare identical calendar fiscal targets and normalize old EPS to the new cutoff share basis. At Q4 roll, compare new FY1 with the previous run's FY2 for that same year; retain both labels and mark the roll. Report absolute/relative revenue, EPS, FCF and operating-income changes and margin percentage-point changes. A rolling NTM change is not mislabeled as an identical-horizon forecast revision.

P80 and P50 are empirical error quantiles from preceding first-tradable forecasts of the same model and assumption hash, only after their outcomes are known at the new cutoff. Minimum eight samples; otherwise insufficient_history. Relative bands require positive comparable forecast denominators. GM uses absolute ratio errors. Base projections are not changed by interval calculation. Annual and NTM bands use realized complete target aggregates. No claim of 80% guaranteed coverage is made; sparse, overlapping observations and regime shifts limit calibration.

## Limitations and evaluation policy

Evaluate revenue, GM, operating income, EPS and engine FCF at 1Q, 2Q, 4Q, FY1 and FY2. Report errors, bias, dispersion, worst misses, extreme misses, revision/forecast volatility, failures and sample counts for A/B/C separately. A zero actual denominator makes percentage error unavailable; sMAPE is also unavailable if both values are zero. GM basis-point errors are the primary margin interpretation.

Annual aggregation, persistent tax assumptions, net-nonoperating-income ratios, robust historical cash conversion and simple growth decay are approximations. They are not NVIDIA management forecasts beyond stated guidance. Do not change V1 to improve its historical scores; a methodologically justified successor must retain V1 and its outputs. Future return fitting, analyst consensus dependence and trade recommendations are outside M2.
