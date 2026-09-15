# RegimePolicyV1 — deterministic NVIDIA fundamentals

M1/M1.1/M2 are PM-accepted and unchanged. M3 reads only eligible GAAP financial facts and the frozen M2 Guidance Anchored Baseline first-tradable cohort. The complete policy JSON is stored in a content-addressed formal assumption set; its units, financial rationale and version are retained. Parameters are fixed before historical classification, not fitted to prices, returns, expected historical labels, or evaluation outcomes.

## Financial features and denominators

Revenue, EPS and FCF growth compare the current quarter with the same prior-year quarter; revenue also compares sequentially. Every EPS observation is normalized to the cutoff's known split basis. NTM uses the preceding four actual quarters; FY1 compares with the preceding fiscal year; FY2 compares with FY1. Aggregate EPS is net income divided by day-weighted diluted shares. A positive denominator is required; EPS/FCF baselines below 1% of comparable revenue are unavailable rather than explosive percentages. EPS's floor is revenue per diluted share, so a split cannot change eligibility. Monetary denominators below USD 1 are unavailable. Forecast growth and revision percentages use the same guard.

Latest, 2-quarter and 4-quarter revisions compare current FY1 with the identical fiscal-year target in the earlier forecast (including its FY2 at a roll). They are endpoint changes, not sums of differing rolling NTM windows or different fiscal-year targets. Missing same-target forecasts stay unavailable. EPS uses the current split basis; margin revisions are fractions, not percentage growth. Revision breadth is the fraction of available five metrics above zero, with explicit denominator coverage. Revisions require exact quarter separation.

Operating leverage = change in operating income / change in revenue. Require an absolute revenue change of at least 2% of prior revenue; otherwise unavailable. DSO uses period-end receivables / quarterly revenue × actual fiscal-quarter days, an explicit endpoint approximation. Cash features include FCF margin and growth, AR/inventory growth, capex/revenue and SBC/revenue. Missing values are never written as zero.

## Layer A: signed scores

All five state scores lie in [-1,+1]; positive deterioration means worse, positive other scores means stronger. Each underlying available feature is clipped to this interval after linear centering/scaling. Available members within a group receive equal weight; a wholly absent group stays unavailable. Data quality separately penalizes sparse groups, so reweighting available features does not imply complete evidence.

Growth centers at 10% annual growth: a transparent healthy-growth reference, not a classification cutoff. Revenue reaches +1 at 60% growth; EPS/FCF allow wider 75/100 percentage-point scales because operating leverage/cash timing amplify them. Revision scales of 15% and 3 percentage points distinguish economically material changes from noise. Profitability combines gross/operating/FCF margin levels and their YoY directions. Margin centers 45%/15%/10% and scales 30/30/25 points represent profitable fabless economics while leaving downside room. These are NVIDIA research priors, not universal industry facts.

Cash quality combines FCF margin, FCF growth relative to revenue, working-capital growth relative to revenue, and SBC/revenue. A 30-point growth divergence is material working-capital stress, not proof of fraud or permanent impairment. SBC's 5% center and 10-point scale track dilution burden, not a valuation adjustment. Deterioration combines negative growth, revisions, margin direction and cash quality. Operating leverage and DSO are disclosed diagnostics rather than independent votes duplicating existing margins/working-capital inputs.

## Layer B: transparent prototype confidence

The five financial-state prototypes and layer weights are fully listed in policy_v1.json. Growth and revisions each have 30% weight, profitability 20%, cash quality and deterioration 10% each. Each prototype gets exp(-weighted squared distance / 0.35). Normalize positive scores, then shrink toward a uniform distribution over eligible regimes according to forecast confidence. Six-decimal probabilities sum exactly to one; rounding residual goes to the largest component, ties follow the documented neutral-first order.

These probabilities are **deterministic regime confidence score normalization**, not statistically calibrated event probabilities. Structural Deterioration has zero model weight until its evidence guard is satisfied; this means policy ineligibility, not proof that structural risk is impossible. Confidence combines feature coverage, anomaly penalties, M2 already-realized sample counts, median absolute relative errors and current relative interval widths. Twelve samples receives full history weight, zero receives only 35%; error/interval penalties reduce confidence further. M2 evaluation label tables are never accessed. Every error sample must originate before the cutoff and have realized financial data available by the cutoff. Confidence never improves by dropping an unavailable core FCF input.

## Structural versus cyclical

Structural eligibility requires FOUR consecutive fiscal quarters of stress, each with at least three independent dimensions: negative revenue growth; both revenue and EPS revisions below -5%; operating-margin contraction beyond 2 points; FCF-margin contraction beyond 2 points. Growth and revision stress are mandatory. Missing history or a quarter gap breaks the streak. One shock, one EPS miss or one inventory anomaly cannot pass. This is a conservative quantitative proxy for persistent deterioration, not evidence establishing competitive-position changes or permanent business-model damage. The engine does not claim to measure qualitative competitive stability.

## Persistence and cycle

Primary regime is the confirmed state; candidate is the largest instantaneous normalized confidence component. They may differ while a transition is pending, and both are displayed. A borderline candidate needs two consecutive quarterly snapshots with confidence >=40%. Immediate transition requires a probability lead >=25 points, confidence >=65%, and at least two independent supporting state scores beyond 0.2. A strong negative override requires growth, revision and profitability all <=-0.65 and quality >=60%; it selects Cyclical Downturn unless structural eligibility already holds. Structural guard always takes precedence over overrides. Sparse data cannot trigger confident transitions. Initial state uses the candidate, with low confidence disclosed; no initialization event is counted as a state change.

Transitions are append-only and reference their two immutable snapshots. effective_at and detected_at are the first-tradable detection checkpoint, never backdated to a candidate's first appearance. created_at is actual reconstruction time. Both timing meanings are retained.

Cycle Score is a separate [-100,+100] weighted composite of growth acceleration (20%), revisions (30%), margin direction (20%), working-capital divergence (15%), FCF divergence (15%). It does not change the structural guard or use valuation. Missing cycle components reduce coverage and remain explicit.

## Replay, sensitivity and limitations

Replay selects at most one formal M2 A run per quarter, at or before cutoff, and processes chronological first-tradable checkpoints. A direct late-date CLI request reconstructs prior eligible quarters first, so hysteresis does not depend on call order. Snapshots and transitions are immutable; policy changes create a separate content-addressed cohort. Historical results are research reconstructions, not live classifications actually published then.

Before viewing labels, sensitivity is specified as +/-10% changes to score centers/scales, each layer weight individually, and transition lead threshold. Recompute full transition paths independently; report changed-label fraction, probability and cycle changes, transition count and flip rate. More than 25% label changes in any case is flagged as sensitivity risk, not tuned away. These perturbations do not vary data-selection, denominator-safety or structural minimum-history rules.

Valuation is allowed only in a separate read-only combined report after classifications have been computed. The classifier cannot access price, valuation, DCF, Future Outcomes, forecast evaluation labels, AI features, sentiment or analyst targets. There are no trading recommendations, opportunity scores or return optimization. All formula limitations and historical sanity findings must be reported without hand-editing labels.
