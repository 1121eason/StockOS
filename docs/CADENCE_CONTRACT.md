# Read-only cadence input contract

Cadence consumes existing formal research artifacts. It does not ingest filings,
normalize financial facts, run a provider, rebuild forecasts/Regime, or commit
snapshots. `dry_run=False` is rejected before database access. The dry-run receipt
states which work was actually performed.

## Exact formal cohort

The existing formal resolver selects one company/anchor/checkpoint forecast and
its exact valuation and corrected `RegimeOutputV1.1` snapshot. A date with multiple
eligible checkpoints requires an explicit timezone-aware checkpoint. The complete
Regime envelope and its lineage are retained in `regime_context` even when a
revision is unavailable and no decision can be emitted.

## Explicit forecast revision target

`CadencePipelineConfig.revision_target` is an explicit fiscal target such as
`FY2027` or `FY2027-Q3`. It has no default. `FY1`, `FY2` and `NTM` are not target
identities and are not accepted as this selector. Choosing the default business
horizon remains a policy decision.

The reader consumes exactly one `forecast_revisions` row for the selected formal
run. It verifies the producer identity key, metadata run IDs, and the same-company,
same-type/model/version/assumption strictly earlier predecessor selected by
`research.service.revisions`. It rejects a stale predecessor, future information,
ambiguous rows and malformed metadata. It never selects a global latest revision
or regenerates a missing one.

It reads `comparisons` and selects exactly one identical fiscal target. Annual
FY2-to-FY1 label rolls are preserved; quarter targets require quarter labels.
Revenue, EPS and free-cash-flow percentage changes remain separate and signed.
Split factor, labels, both run IDs, timestamps and revision ID appear in the
receipt. No maximum across targets is computed and no missing number becomes zero.

Direction remains revenue-led, matching the existing consumer.
The existing cadence upward label (> 5%) and fusion downside trigger (< -3%) are
retained. The fusion's existing 8% upward-bonus threshold and all allocation
coefficients/caps are unchanged. The comparison is a quantitative forecast
revision; this linkage does not establish management-guidance attribution.

Missing selection, missing stored revision or missing target produces an
`UNAVAILABLE` revision receipt. A selected comparison with a null metric produces
`INCOMPLETE` and preserves each known/unknown metric. In both cases cadence returns
`INCOMPLETE_REVISION_CONTEXT`, `decision: null`, and null recommended action/equity/
cash fields. Fusion is not called. Genuine stored zero changes remain available.
Invalid or ambiguous selected inputs raise `ValueError` before fusion.

## Human review and candidate quarantine

The established M4 review contract counts the latest review for each exact
analysis-run/category card in a provider/model-scoped five-quarter set. Its 35-card
completion status includes all verdicts; it is not candidate approval. The schema
has no candidate-cohort mapping or explicit approval decision. The legacy
`cohort_features`/`cohort_challenges` interface has no verified formal-run,
completed-analysis, evidence-admission or human-approval binding in this source.

Consequently cadence does not open or admit that legacy candidate database. The
review status stays `PENDING`, its receipt explains the missing contract, and all
qualitative inputs remain quarantined. `require_human_review=False` cannot supply
missing provenance or authorize promotion. A complete formal revision permits
only `SUCCESS_DOWNGRADED_QUANT_ONLY`; its top-level AI fair-value/gap outputs are
null. For bridge-format compatibility, the nested `valuation` retains legacy
AI-named fields equal to the pure quant baseline, with zero qualitative score and
no challenge haircut. They are not admitted AI results. The existing M4
advisory-only policy is unchanged.

## Remaining completion requirements

- Approved default cadence fiscal horizon, if an automatic selection is desired
- Candidate producer/schema and immutable formal-run/evidence lineage
- Candidate-to-review/cohort mapping plus explicit acceptance/approval policy
- S2 source/request/attempt lineage and a real approved quality rubric, not fixed scores
- Cadence snapshot destination/schema, identity/idempotency, commit/quarantine rules
- Authorized runtime validation against appropriate consistent data copies

These requirements must be resolved before enabling AI promotion or persistence.
Offline synthetic passes establish the implemented input/guard contracts; they
are not production, semantic-quality or trading-readiness certification.
