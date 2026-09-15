# RegimePolicyV1.1 — confidence and transition contract

M3 received PM Conditional Pass. M3.1 corrects confidence and warning lineage only. The original score weights, prototypes, clipping scales, 40% confirmation minimum, 65% strong-transition confidence, 25-point lead, two-quarter persistence and four-quarter structural guard remain identical. The original document is preserved as [RegimePolicyV1](archive/REGIME_METHOD_V1.md); original snapshots and transitions are never overwritten.

## Evidence Confidence

Use the eligible raw prototype scores BEFORE reliability shrinkage. Evidence Confidence is the equal-weight mean of five bounded components, each weighted 20% in the new formal assumption set:

1. candidate raw probability after normalizing prototype strengths;
2. separation: (largest strength - second strength) / (largest + second);
3. support breadth: among the four independent growth/revision/profitability/cash dimensions, fraction closer to the candidate than runner-up (ties count half; missing dimensions do not count as support);
4. score consistency: 1 / (1 + weighted dispersion of squared prototype residuals / existing temperature);
5. current evidence strength: 1 / (1 + weighted mean squared prototype residual / existing temperature).

Deterioration is included in prototype fit under its unchanged weight but is not counted as an additional independent breadth vote. This describes current vector separation and agreement, not historical accuracy or observation reliability. Equal weights are transparent semantic priors, frozen before corrected historical replay; no coefficient is selected against FY2023 labels or returns.

## Data Quality Confidence and active lineage

Snapshot → scoring feature → required observation / forecast period → transitive raw observations → warning or quality issue. Every edge is saved. The graph distinguishes current actuals, rolling actual denominators, prior same-target forecast observations, current M2 forecast inputs, guidance/bias inputs, and financial error-history evidence. Each source remains PIT gated.

Data Quality Confidence = active observation completeness × (1 - capped relevant quality penalty). An observation in an unavailable historical quarter is a history shortfall, not a current data-quality failure. A missing required metric in an otherwise available quarter or a missing required forecast value is a completeness failure. Economic nonpositive/small denominators are preserved as unavailable ratios without labelling the observed financial value as corrupted.

Only warnings joined to an active scoring feature's observations can penalize it. Share-basis warnings require an exact period/metric dependency, or matching fact IDs. A warning matching only the same historical company or quarter is insufficient. Relevant unresolved basis warnings retain the existing 20% penalty. Other explicitly matched PIT quality issues use the existing 15% severity amount; total remains capped at 50%. Duplicate findings are deduplicated. Registry issues must have been known by the snapshot cutoff (created_at and any stated information_available_at); newly discovered future issues cannot retroactively alter a snapshot. Replay-derived validation warnings are reconstructed from eligible source observations and preserve their validation rule.

Margin anomaly alone is an economic signal, not proof that a measurement is unreliable. Negative FCF or operating margins remain in profitability/cash features and warning output but do not automatically reduce Data Quality Confidence. Explicit parser/source/basis issues on those observations still do. This separates business weakness from data reliability.

Active direct windows follow each formula: current vs prior-year for YoY/margins, current vs prior-quarter for QoQ, four quarters for NTM actual denominator, the prior fiscal year for FY1, and exact 1/2/4-quarter prior same-target forecasts for revisions. M2 forecast dependencies are audited by metric: revenue seasonality reaches 13 quarterly revenue observations; recent ratio/nonoperating/tax/cash inputs reach four quarters, share and OpEx growth five. Reported historical EPS is NOT an input to M2 aggregate forecast EPS, which is calculated from net income and diluted weighted shares. In particular an old EPS observation cannot become relevant merely because revenue from its quarter participates in seasonality. Guidance/bias fact IDs and actual components are preserved. The prior forecasts keep their own cutoff and split basis.

Diagnostic-only DSO, capex/revenue, operating leverage and QoQ do not independently penalize the classification. Forecast-error samples are financial history, isolated from valuation and outcome labels. Unmatched warnings remain retained with explicit exclusion reasons; nothing is deleted from the source quality ledger.

## History Sufficiency

Expose raw sufficiency [0,1] and three components: M2 realized error samples / the unchanged 12-sample reference (capped at 1); presence of exact 1/2/4-quarter revision windows; and availability of the direct rolling actual observations. Raw sufficiency is the minimum, preventing one abundant series from hiding a missing required window. The existing history floor is retained explicitly: history multiplier = 0.35 + 0.65 × raw sufficiency. The floor is not a claim that nonexistent history is 35% complete.

Historical error magnitude and interval width remain visible diagnostics. They are not observation-quality penalties and are not relabelled as current prototype evidence. Their sample counts contribute to history sufficiency.

## Composite, probability vector and transitions

Composite Confidence = Evidence Confidence × Data Quality Confidence × history multiplier. Apply the UNCHANGED transition confidence thresholds to this explicit composite. Low composite resets the qualifying confirmation counter to zero. The full probability vector uses reliability shrinkage only: reliability = Data Quality Confidence × history multiplier; final probabilities = reliability × normalized raw prototype strengths + (1-reliability) × uniform eligible-regime vector. Evidence is already represented by prototype strengths and is not counted twice in probability shrinkage. Six-decimal probabilities sum exactly to one.

All probabilities remain **deterministic confidence-score normalizations, not calibrated event probabilities**. Candidate is the strongest eligible current prototype evidence. Confirmed Regime is the persistence-approved state; primary_regime remains a compatibility alias. Candidate probability and gap to the second candidate refer to the final vector; raw gap is separately included in evidence diagnostics. A fully unreliable vector can be uniform while retaining the raw candidate with LOW_CONFIDENCE.

Transition statuses, in precedence order:

- LOW_CONFIDENCE: composite is below the existing 40% confirmation minimum, regardless of whether candidate equals confirmed.
- STRONG_OVERRIDE_PENDING_GUARD: broad strong negative evidence would favor the structural prototype, but the unchanged structural guard prevents that economic label. Expose blocked_regime=Structural Deterioration; a cyclical override can still be confirmed. No sixth economic regime is introduced.
- PENDING_CONFIRMATION: candidate differs from confirmed and has not completed the existing persistence or immediate-transition rule.
- STABLE: confirmed and candidate agree with sufficient composite confidence, including a transition just confirmed at this checkpoint.

The structural gate always governs eligible labels. If it ceases to hold, the original explicit guard-release rule remains. effective_at/detected_at retain first-tradable historical detection semantics; created_at records reconstruction time. Snapshot fields, confidence diagnostics, active/excluded warnings, confirmation counters and transition rows are immutable under the new policy identifier.

## Downstream contract and validation

Consumers must use the [Regime output contract](REGIME_OUTPUT_CONTRACT.md) as one atomic envelope. Confirmed Regime alone is forbidden. No valuation multiple, signal, opportunity-score or AI behavior is defined here.

Compare all 26 quarters with original M3, including every changed confirmed label/transition, FY2023 Q1-Q4 lineage and confidence decomposition, AI acceleration, FY2025/26, FY2027 and structural/split/PIT regression. Reuse the original +/-10% sensitivity cases and 25% changed-label tolerance without tuning them to the corrected path. Original and corrected stability metrics are reported side-by-side; better-looking FY2023 labels alone are not acceptance evidence.
