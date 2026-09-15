# M2 frozen-policy coverage and interpretation

The frozen V1 produced complete next-quarter, NTM, FY1/FY2 and forward-valuation outputs for all 26 benchmark dates. Forward enterprise DCF is available at 24 dates; the first two dates lack eligible debt under the accepted M1.1 contract.

Reverse DCF is available at 13 dates. V1 requires a positive complete trailing four-quarter FCFF proxy. Its historical proxy accepts effective tax rates in [0,1]; negative rates from real GAAP tax benefits are retained in the source data but not assumed to represent a continuing operating tax rate. V1 does not invent a replacement normalized historical tax rate. Examples include FY2021 Q2, FY2022 Q4 and FY2023 Q2–Q4. A trailing window containing such a quarter remains unavailable. This is a **model applicability limitation**, not a claim that the source tax benefit is erroneous or that the actual financial statement is missing.

The three gates FY2022 Q1, FY2023 Q3 and FY2024 Q1 therefore have incomplete Reverse DCF values. Their financial/forecast/forward-valuation/forward-DCF outputs and all PIT checks remain available and pass. FY2025 Q2 and FY2027 Q2 also have converged Reverse DCF values. `reverse-input-readiness.json` records every component and reason.

The execution report distinguishes numerical completeness from timing safety. M2 Task 34 explicitly permits NULL historical DCF values when required inputs are insufficient; acceptance checks do not reinterpret a NULL as a computed number. The report preserves PARTIAL completeness where applicable. No coefficient, historical tax observation or source-selection rule was changed after seeing coverage/accuracy.

DCF/Reverse DCF use an enterprise-compatible NOPAT cash-conversion proxy. It remains an approximation to detailed FCFF, particularly around unusual tax/nonoperating/noncash items. A future historically normalized tax policy would be a separately versioned methodological choice, not an overwrite of V1 and not an adjustment selected against stock returns.

All stored display ratios use eight decimal places. Reverse root dollar residuals are saved; the exact ratio derived from the stored residual and enterprise value is independently verified in `solver-audit.json`, rather than treating a rounded displayed zero relative residual as exact zero.
