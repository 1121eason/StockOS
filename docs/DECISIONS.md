# Decisions

## D1 — Point-in-time facts and immutable calculations

Decision: append-only facts and calculations, SQL-level UPDATE/DELETE guards, source hashes and explicit cutoff selection.
Reason: preserve historical evidence and prevent later estimates rewriting a backtest.
Alternatives: mutable wide quarterly table; rejected because it erases vintages.
Trade-offs: more storage and explicit snapshot selection.
Date: 2026-09-12.

## D2 — Physically separate outcome labels

Decision: distinct databases, ORM metadata and migrations for feature data versus future outcomes.
Reason: an accidental feature SQL query must not see label tables.
Alternatives: a naming convention within one database; too easy to bypass accidentally.
Trade-offs: no cross-database foreign key; production must use separate roles.
Date: 2026-09-12.

## D3 — Conservative availability bounds

Decision: date-only releases use next midnight ET; SEC acceptance uses a documented buffer.
Reason: no exact intraday timestamp was established for the downloaded historical releases.
Alternatives: hard-code 16:20 ET for every quarter; rejected as unsupported precision.
Trade-offs: intraday/evening known-information sets are incomplete. This is a PM-visible PIT data limitation, not a claim of exact timestamps.
Date: 2026-09-12.

## D4 — FCF definitions kept separate

Decision: engine FCF = operating cash flow minus purchases CapEx. NVIDIA-reported FCF is a separate source metric; it also deducts principal payments on equipment/intangibles.
Reason: the user's requested deterministic formula must remain explicit.
Alternatives: overwrite the engine metric with management's number; rejected.
Trade-offs: differences are documented and flagged instead of being treated as parser errors.
Date: 2026-09-12.

## D5 — Default stack and pinned dependencies

Decision: Python >=3.12, uv, SQLAlchemy 2, Alembic, Pydantic 2, pandas, Typer, httpx, pytest, Ruff and mypy. Tested here on Python 3.14.6.
Reason: standard relational/data tooling; minimal service footprint.
Alternatives: production PostgreSQL deployment now; deferred since local execution is sufficient for M1.
Trade-offs: PostgreSQL DDL/offline migration validation is not equivalent to live PostgreSQL acceptance.
Date: 2026-09-12.

## D6 — Bootstrap prices are not historical raw prices

Decision: replaceable Yahoo Chart JSON adapter; label split-adjusted/current-vintage status explicitly; prohibit historical fundamental valuations from consuming these prices.
Reason: adjusted prices and original EPS/shares can create incorrect historical multiples.
Alternatives: silently assume raw prices; rejected. Paid vintage provider not selected.
Trade-offs: basic ratios are implemented but real historical valuation rows can be NULL until approved price/share basis is available. No vendor lock-in.
Date: 2026-09-12.

## D7 — Split guards and no invented classifications

Decision: suppress EPS comparisons crossing July 20, 2021 or June 10, 2024 until a complete action/basis adapter is present. GICS fields and confidence remain NULL without sourced licensing/classification evidence. The requested NVDA archetype is seeded directly.
Reason: retain unknowns; don't conflate share restatements with growth.
Sources: [NVIDIA 2021 split FAQ](https://investor.nvidia.com/files/doc_downloads/doc_faq/06/21/NVIDIA-2021-Stock-Split-FAQ.pdf), [NVIDIA 2024 split FAQ](https://investor.nvidia.com/files/doc_downloads/2024/06/nvidia-2024-stock-split_faq_investors.pdf).
Alternatives: guessed historical adjustments or classification scores; rejected.
Trade-offs: incomplete EPS growth series and classification metadata.
Date: 2026-09-12.

## D8 — Scope stop

Decision: transparent next-quarter forecast only; typed hooks for DCF, reverse DCF, scenarios, regimes and Opportunity Score. No trading decision output.
Reason: M1 proves the data/forecast architecture before model calibration.
Trade-offs: genuine historical annual forecasts/forward multiples remain unavailable.
Date: 2026-09-12. PM review is required before starting the next milestone.


## PM Final Closure decisions

The PM accepts minute-level issuer-distribution timestamps with end-of-minute bounds and verified research_reconstructed prices. An independent raw-price vendor and historically observed Wall Street annual forecasts are not M1.1 requirements. Future internal deterministic forecasts remain the planned primary forward-valuation inputs; no forward valuation is implemented in closure.

Market cap uses the latest known eligible share observation, not necessarily the new quarter-end share count. Filter by availability first, then choose the most recent share economic date; apply cover/structured/official priority on the same date and latest eligible revision within equal priority. Simultaneous equal-priority conflicts return unavailable. Older known observations are allowed with dates and age preserved. Weighted-average diluted shares are excluded.

Cash/debt may use the last known disclosed complete balance, with economic date and carried_forward provenance. Missing debt is not zero. EV can be explicitly incomplete when components are unavailable. The remaining final-acceptance blockers are real SEC ingestion/reconciliation and eligible real share observations, followed by the three PM gates. Architecture remains accepted; M2 remains deferred.

## M2-ADR-001 — additive deterministic research layer (2026-09-12)

PM accepted M1/M1.1 Final Pass and authorized M2. Preserve the accepted PIT/source/split/share/timestamp rules. Add immutable forecast runs/periods/assumptions/revisions and research valuation/scenario children, core migration 0005; add financial forecast evaluation labels to the separate labels database, migration 0003. Legacy forecast and valuation rows remain available. New model identities are ForecastPolicyV1, DCFPolicyV1, ReverseDCFPolicyV1, ValuationPolicyV2.

Select simple fixed A/B/C policies before full historical accuracy evaluation. No coefficient is selected against future returns. An initial single-quarter development smoke snapshot is retained; the final frozen-policy assumption hash defines the benchmark cohort. A no-loss-tax-benefit policy was made explicit before accuracy evaluation, not fitted to outcomes.

Use NOPAT cash-conversion FCFF proxy for enterprise DCF; reported CFO-capex is not silently treated as unlevered FCFF. Separate EPS diluted-weighted shares from market-equity shares. Prior realized calibration is recomputed from financial facts and prior forecasts, never from the evaluation store. Annual revisions compare the same fiscal year across label rolls. Historical context excludes the current and future observations. No M3 work is authorized by this change.

M2 implementation audit: assumption storage uses `typed-assumptions-v1`, assigning concrete ratio/count/quarter/year/timestamp/identifier units to every fixed parameter. The parameter values in the frozen policy file are unchanged. Preliminary development rows with the earlier generic unit declaration remain immutable; final replay/evaluation explicitly selects the typed assumption hash. This is a provenance correction, not accuracy-based tuning.


## M2 correctness fix — equivalent timestamp representations

The final relocated CLI check exposed two identities for the same first-tradable instant when the CLI accepted UTC but chronological replay supplied America/New_York. FinancialInputs already normalizes its cutoff to UTC; the outer forecast identity payload still retained the caller's offset. M2 now serializes first-tradable instants exactly as the historical coordinator does, and other checkpoints use the normalized UTC cutoff. This preserves every frozen historical run identity and all model coefficients and numerical outputs. The accepted M1.1 timestamp-selection/calendar rules are unchanged. Three new tests cover UTC, New York and Brisbane representations across first-tradable, issuer-release and research-replay checkpoints; the relocated bundle compares the complete forecast, periods, revisions and valuation at three actual gates.

## M3 V1 implementation and historical sanity review

RegimePolicyV1 and its method were frozen before historical classification. The first replay showed clear downturn candidates and strongly negative cycle scores in FY2023 Q2/Q3, but the confirmed Growth state was retained: the second candidate's confidence is 39.456%, below the frozen 40% minimum. This result is retained and highlighted as a persistence tradeoff, not corrected by lowering a threshold after observing labels. The engine identifies the pressure; its primary state alone understates this interval.

A synthetic boundary review separately found that low-confidence candidates were counted in the confirmation streak even though a transition required the CURRENT confidence to pass. The documented policy requires two qualifying quarters. RegimeEngineV1.1-confidence-streak resets the streak to zero whenever current confidence is below the unchanged 40% minimum. This is an implementation correction, not parameter tuning; the formal assumption payload names the implementation revision. Initial development snapshots remain immutable, and the final cohort is separately identified. No accepted M1/M1.1/M2 records or parameters change.

Structural probabilities denote eligibility under a conservative four-quarter quantitative guard. If that guard ceases to hold, an existing structural primary state is released rather than being retained with zero eligible support. This explicit safety release is part of the transition implementation, with reason STRUCTURAL_GUARD_RELEASED.

## M3.1 confidence and downstream contract

- M3 PM Conditional Pass accepted. RegimePolicyV1.1 / RegimeEngineV1.2-active-lineage corrects confidence semantics; original policy coefficients and financial features remain identical. Equal evidence component weights were frozen before replay.
- Registry issues are PIT-gated and matched to exact active observation lineage; historical warnings remain retained. Negative margins alone are economic evidence, not source unreliability.
- Persist confirmed/candidate/status and separate confidence components; require atomic RegimeOutputV1.1. Default CLI selects corrected version; V1 remains explicit.
- Corrected path changes are accepted as observed, without threshold tuning: FY2023 Q2 downturn and FY2024 Q1 Hypergrowth. Detailed chain attribution and all acceptance evidence are in MILESTONE_3_1_EXECUTION_REPORT.md. No subsequent milestone is authorized here.

## M4 implementation and open execution inputs

- Per M4 PM instruction, M1–M3.1 are accepted. Existing Quant/Regime methods and history remain unchanged.
- Separate AI analysis/evidence/features tables from the legacy M1 ai_features placeholder; use full versioned provenance and completed-snapshot admission.
- Common favorable polarity, explicit NULL for no evidence, wrapper confidence and persisted contradiction. AI cannot calculate Quant outputs or apply proposals.
- Use a 200-day source window: two releases, two filings and one official transcript/Q&A/presentation. Unknown corrected-transcript publication time is not backdated to call time. SEC acceptance alone is not exact publication; use an explicit conservative next-midnight filing-date bound.
- Exact prompts/raw structured responses/settings are persisted. Actual provider/model/version must be configured locally; no test fixture is promoted as historical AI.
- Five-quarter human review template is pending, not a completed review. Live semantic performance and Final Pass require real outputs and human evidence. Modern-model training-data contamination remains a disclosed historical-analysis limitation.
