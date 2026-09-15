# AIAnalystPolicyV1 — NVIDIA AI Analyst

Quant calculates. AI interprets. M1–M3.1 are PM accepted. M4 reads, extracts, interprets and challenges official disclosures; it cannot calculate or change forecasts, valuation, regime, Cycle Score, signals or allocations. No return fitting or cross-company intelligence is introduced.

## Boundary and execution

`quant/ai_context.py` is a read-only whitelist over existing deterministic modules. It provides the immutable formal M2 forecast, realized guidance-bias samples available at that cutoff, financial features, deterministic anomaly codes and the complete RegimeOutputV1.1 envelope. It does not query prices, valuations or outcome tables. `ai/` receives that context as plain data; providers receive no DB handles, browser, tools or write capabilities. The separate CLI combined research view adds existing valuation fields only AFTER AI processing; that view never feeds the provider. Quant has no dependency on provider availability.

Stages: official narrative retrieval → Pass 1 exact evidence extraction → exact-span admission → Pass 2 feature synthesis → evidence/direction/confidence checks → advisory model/regime/anomaly challenges → append-only normalized records and snapshot. Failed or invalid calls are bounded to two attempts and recorded without inventing fields. If any stage fails, there is no completed snapshot. Intermediate admitted evidence/features may remain as audit rows; formal consumers MUST join a completed `ai_analyst_snapshots.analysis_run_id`. They must not consume intermediate rows from failed runs.

## Source hierarchy and PIT

Only NVIDIA issuer domains and NVIDIA SEC primary documents are permitted. Tier 1: earnings releases, filings, exhibits and presentations. Tier 2: issuer-hosted official transcripts/Q&A. XBRL accession extracts and companyfacts are not treated as prose documents. Social media, news opinions, analyst recommendations and stock commentary are outside the corpus.

Each quarter uses the existing first-tradable formal forecast timestamp and information cutoff. A declared 200-day active source window includes the two most recent eligible releases, two eligible filings/exhibits, and one eligible official call/Q&A/presentation. A later filing is never substituted merely because it discusses the same quarter; the latest eligible filing can be from the previous quarter. This bounded V1 corpus is not an exhaustive full-history search; annual structural context older than the window may be missing.

Existing publication evidence supplies availability. Where SEC primary HTML has a linked accepted filing but no independent publication evidence, use a conservative bound: later of acceptance plus one minute and next midnight America/New_York following filing_date. Label it `date_only_SEC_filing_bound`, with published_at unknown; do not label acceptance as exact publication. Unknown timestamps are excluded. Changed-content pages cannot inherit an earlier date. AI-specific new evidence uses scope `ai_narrative` so it cannot alter accepted financial availability or Quant lineage.

Raw source hashes are verified before parsing. Issuer releases use only their article body, preventing contemporary navigation/related news leakage. Hidden HTML/XBRL contexts, tables and price/stock-return paragraphs are excluded. SEC narrative remains available. PDF blocks preserve page pointers. Transcript V1 retains only identified NVIDIA management turns, excluding analyst opinion turns; unidentified speakers remain a coverage limitation. A corrected transcript's call date is NOT proof of that revision's upload time. If historical publication cannot be verified, retain the discovery record and mark missing in historical context.

## Taxonomy and polarity

All features use [-1,+1], with `direction=positive_is_favorable`. Negative means adverse fundamental outlook. `supply_constraint` deliberately means the OUTLOOK from constraints: positive relief, negative binding constraint, never a positive demand proxy. Existing primary snapshot fields are projections of normalized features, not a second calculation.

Operating: demand_momentum, demand_visibility, pricing_power, supply_constraint, product_cycle_strength, customer_adoption, customer_concentration_outlook, inference_demand, training_demand.

Competition: competition_outlook, custom_asic_outlook, customer_insourcing_outlook, ecosystem_strength, switching_cost_strength.

Financial quality: margin_outlook, working_capital_quality, customer_financing_quality, revenue_quality, inventory_quality.

Regulatory/geography: china_outlook, export_control_outlook, regulatory_outlook.

Management: management_confidence, guidance_visibility, management_credibility_signal.

Structural: structural_outlook, moat_strength_signal, long_term_demand_durability.

Zero is permitted only for evidence-backed neutrality/mixed evidence. No evidence means NULL in snapshot projections and an explicit missing-feature entry; it is not an observed zero. Every admitted feature has topic-aligned evidence, value, direction, horizon, wrapper confidence, source IDs, model/prompt versions and creation timestamp.

## Evidence and contradictions

Pass 1 stores exact short span, block/section/page pointer, source ID/hash, span hash, publication/availability, topic, speaker when substantiated, implication, statement type and extraction certainty. Spans must be literal substrings of the specific request's eligible block, at most 55 words/500 characters. Unknown IDs, fabricated quotes, unsupported speakers and unsafe source spans are quarantined in `ai_unsupported_claims`. Duplicate spans are deduplicated.

Pass 2 saves supporting and contradicting references separately with a normalized join table. The wrapper adds opposing/mixed Pass 1 evidence for the same topic even if synthesis omitted it. Favorable/adverse signed assessments require a matching implication. Narrative summaries/challenges require admitted evidence references. Interpretation is explicitly a hypothesis, not verified causality.

Source-pointer validation proves that a quote exists; it does not by itself prove semantic entailment of a model's interpretation. Human review remains required to measure unsupported conclusions and omissions. No zero-hallucination claim is made from schema validation alone.

## Confidence policy

The model cannot submit an authoritative numeric confidence. Wrapper confidence is:

mean(directness × bounded extraction certainty × source quality) × independent-evidence factor × contradiction factor.

Directness: reported fact 0.95, management statement 0.80, conditional risk disclosure 0.65. Certainty: explicit 1.00, qualified 0.80, ambiguous 0.50. Source quality: Tier 1 1.00, Tier 2 0.90. Evidence factor: one distinct source/block 0.65; multiple blocks from one source 0.85; multiple source hashes 0.95. Contradiction multiplier is 1 − min(0.5, distinct contradicting span count / admitted item count). Identical quote hashes are deduplicated across sources before confidence calculation; repetition within a block or another copied source cannot raise confidence. Values are policy-constrained research confidence, not calibrated probabilities. Extraction certainty and statement-type labels remain model classifications, bounded rather than accepted as a self-reported probability.

Overall qualitative confidence divides summed supported feature confidences by the full taxonomy size; missing coverage therefore cannot masquerade as complete confidence. Semantic confidence is not financial measurement quality, and cannot overwrite Regime confidence.

## Numbers, guidance, credibility and challenges

Model-authored summaries/rationales/descriptions cannot introduce numeric prose. A conservative lexical guard rejects digits and common numeric terms; numeric financial facts remain in verbatim evidence or immutable Quant context. This guard does not establish complete natural-language semantic correctness; human review covers semantic mistakes and evasive paraphrases. Unsupported numeric assertions are quarantined. Model-generated feature values are qualitative scores, not fabricated financial figures.

Guidance semantic features summarize demand/management/guidance visibility without rewriting numeric guidance. `combined_credibility_view` displays existing Quant guidance accuracy alongside the AI credibility signal. Its combined score is NULL and research-only; the AI signal is not a standalone management-credibility score.

Challenges are upside/downside/anomaly/regime/adjustment with direction, affected model variable, horizon, evidence IDs and wrapper confidence. Anomaly explanations must reference an existing context anomaly code and do not clear that code. Structural interpretation is evidence-bound, not an automatic reclassification. Model proposals persist target model/variable, rationale, evidence, confidence and status `proposed`; suggested numeric ranges are NULL in V1. There is no automatic acceptance or application endpoint. Future review workflow may append reviewed/rejected/accepted_for_future_policy decisions under a later policy; these names do not authorize M4 to update Quant.

## Injection, versioning and provider abstraction

Documents/evidence are untrusted data in a separate payload; trusted system policy is never sourced from documents. Suspicious instruction-bearing paragraphs are quarantined before model context. Providers have no tools. Output schemas forbid extra fields and unsafe trading/price content is rejected. These layers reduce injection risk; lexical filters cannot prove universal model immunity.

AIAnalysisRun, calls, events, evidence, features, evidence joins, snapshots, challenges, proposals, unsupported claims and human reviews are append-only under SQLite/PostgreSQL triggers. Exact system/task/data/schema prompts, provider/model/version, available settings, raw structured response and response hash are persisted. Reusing an identical completed request returns its snapshot; refresh/model/prompt changes create new runs, never updates. RecordedProvider requires an exact prompt hash and preserves original provider identity; synthetic test fixtures are never historical AI results.

OpenAIProvider uses the official [Responses structured-output contract](https://developers.openai.com/api/docs/guides/structured-outputs), with strict JSON schema, no tools, `store=false`, configurable supported reasoning/temperature and bounded output. The actual returned model version must equal the locally configured pinned version. A missing key, refusal, truncation, invalid schema or version mismatch fails safely. Other implementations can satisfy `AIProvider.analyze_document`, `extract_evidence`, `synthesize_features`, `generate_challenge` without changing core persistence.

## Evaluation and human review

Start with FY2023 Q2/Q3, FY2024 Q1/Q2, FY2025 Q4, FY2026 Q1 and FY2027 Q2; expand to all 26 only after representative outputs are reviewed. Prepare all source contexts independently of provider credentials. The five-quarter review template contains demand, supply, competition, product cycle, management, anomalies and model challenge, with correct/partially_correct/unsupported/missed verdicts and reviewer identity. Empty templates and automated tests are NOT completed human reviews. No future stock return is used for evaluation.

Coverage, schema validity, exact-span rejection, contradictions, semantic support/omissions and repeated-response consistency must be reported separately. A live historical feature table, earnings-call findings and semantic hallucination rate remain unavailable until real provider responses and review evidence exist. Do not claim M4 Final Pass based on fixture tests alone.

## Historical model limitation

PIT filtering constrains the retrieved documents and structured context, not the model's training data. A modern model may already know later events. The prompt forbids use of that knowledge, but tests cannot prove it is absent from weights. Actual historical semantic review must look for unsupported later-event references; this is a remaining limitation, not a claim of a historically trained model.
