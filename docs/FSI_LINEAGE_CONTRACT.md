# S2 candidate lineage contract, engineering format 2

## Scope and unchanged research decisions

The canonical backend is based on `cbb78db1ea0fe8fef8565d855605c7696cb13f3c`.
The sanitized Mac source handoff is `c17cb8da0b54689b99bf6772e715887cf3d268d5`.
Its experiment scripts were not evidence of completed research. In particular,
fixed scores and a fixed superiority verdict cannot establish quality.

Formal contracts, prompts, service orchestration and review selection are restored
to the canonical backend. The 55-word evidence bound and confidence coefficients
are unchanged. Confidence now refuses incomplete provenance/classification rather
than inventing source identities or assigning a fallback score. Formal review
selection never substitutes another provider or model for the requested one.

The five human blind-review dimensions in `FSI_S2_EXECUTION_WORKORDER.md` are
unchanged. No numeric scale, weighting, aggregation, reviewer quorum, tie-break,
significance threshold or promotion rule is invented. All scores are null, the
winner is null, and quality is `UNSCORED`. Counts, narrative length and mechanical
admission are not quality ratings. Cohort research remains a candidate.

## Explicit candidate prompts

The handoff supplies an FSI-enhanced global prompt, not an independently frozen
full historical Method B prompt. `S2ExperimentalPromptV1-B` and
`S2ExperimentalPromptV1-C` are new engineering candidates using the handoff's
instructions and a common canonical `FeatureSchemaV1` / `AIAnalystPolicyV1`
admission contract. The FSI system extension is included once for C and omitted
for B. Both keep the common strict roles and stage tasks. The workorder's intended
PromptSetV6 labels are recorded separately; they are not the executed versions.
`comparison_design_status=UNVERIFIED_FROZEN_BASELINE_MISSING` means historical
B/C reproduction and scientific comparison eligibility remain unverified.

## Fresh storage and no silent resumption

- No formal database is opened by either runner. Inputs must be supplied explicitly.
- Dry-run defaults to zero provider calls and no filesystem/database writes.
  Missing inputs report `UNVERIFIED_MISSING_INPUTS`, never readiness or a schema pass.
- Live CLI and programmatic `LIVE_EXECUTION` are blocked before source, provider,
  database or output access. Reserved `--live --authorize-live`, `--model`,
  `--prepared-context`, `--source-dir` and `--output-dir` flags are insufficient to
  unlock them. A reviewed frozen methodology and global single-process /
  no-residual-provider runtime contract are still missing. No live-ready claim is made.
- Synthetic cohort execution uses a new exclusive output directory to prevent
  reusing an existing run. This is not a global provider-process lock. No stale-lock
  deletion, overwrite, checkpoint reuse, automatic S2 seeding or outer retry exists.
- Format 2 is created only in a new candidate file. Legacy databases are refused,
  never auto-migrated. No production schema migration is part of this change.
- A single method permits at most 22 attempts; a B/C invocation permits at most 44.
  More than 20 extraction chunks fail before calls, rather than truncating sources.
  Provider-internal network behavior is not independently measured by these
  wrapper attempt counts. No live B/C invocation is currently available.

## Supplied input and exact lineage

Prepared context retains the existing `quant_context` and `sources` shape.
`quant_context` requires an aware `information_cutoff`, matching `quarter`, and
`anomaly_codes`. Each source document requires its true content SHA-256,
`source_document_id`, `document_type`, `published_at`, `available_at` and `tier`.
Raw files in `--source-dir` are named by their lowercase SHA-256, with no path
components. Source bytes are rehashed and re-parsed with the existing source
parser. Supplied blocks must equal the complete eligible parsed block set,
including their actual source hash, block ID and metadata. Future availability,
duplicate identity, omitted blocks, altered text and hash mismatch are rejected.

Each candidate run stores:

1. Exact prepared context, context hash, actual method configuration, source bytes,
   source document metadata and full blocks.
2. A pending call row committed before invoking the provider, with the complete
   exact request and the canonical service digest of `[stage, request]`.
3. The actual JSON provider response, response digest, reported model/usage when
   present, final status and duration. Missing responses/model/usage remain null;
   exception text is not logged. A crash leaves a pending attempt counted.
4. Each admitted quote linked to this run's extraction call, returned draft key,
   source document/hash, actual block ID, exact span/hash and admission metadata.
5. Each feature/challenge linked to its stage call, validated raw structured output
   and run-scoped evidence. Rejections are retained. No evidence is selected by
   method alone or borrowed from a prior run.

Responses are schema-validated; exact source spans, matching topic/polarity,
nonempty directional support, disjoint final evidence roles and narrative guards
are reapplied. Confidence uses admitted provenance only. Failed provider/schema
calls stop without retry. Missing features or mandatory challenge categories
remain `INCOMPLETE`; `COMPLETED` means only the candidate engineering stages ran.

## Read-only verification

`scripts/verify_fsi_lineage.py --database PATH --run-id N [--run-id M]` opens an
existing SQLite file with `mode=ro&immutable=1` and `query_only`. It refuses sidecars,
legacy formats and absent/ambiguous selections. It rechecks source bytes/blocks,
full request/response digests, stage/run binding, and every admitted or rejected
raw draft in order. It compares the complete replayed admission/rejection ledgers,
stored payloads and receipt counts, and checks the database bytes stayed unchanged.

`lineage_status=CONSISTENT` is only a consistency result for supplied local
artifacts. Overall status stays `UNVERIFIED`; exit code 2 reflects unresolved
proof, and exit code 1 means inconsistent/malformed lineage. Honest failed,
incomplete or pending runs receive `lineage_status=UNVERIFIED` after attempt
accounting, not a completed-run consistency verdict. This is not a
cryptographic external attestation. Provider model identity, official source
ownership, original PIT availability metadata, past database preservation,
research quality and historical B/C reproduction are not proven.

The existing `verify_fsi_s2_offline.py` retains its legacy consistency-only contract.
No old rows are repaired with invented responses, evidence IDs or hashes.

## Human reviews and remaining inputs

Formal human-review cards keep the existing seven categories and four verdicts;
these are not a numeric S2 blind-scoring scale. The worksheet/import tools require
explicit run/snapshot and dossier binding. Human values are blank until supplied,
and cross-run evidence or mismatched inputs cannot be silently imported. Batch
validation/import applies to Part 3 formal review cards only; optional Part 1/2
forms are supplemental historical materials, not validated or imported as S2 scores.

Still needed before a scientific quality or promotion conclusion:

- The independently frozen historical B/C prompts and their approved exact schemas.
- Authentic source-package/PIT provenance and recorded live provider identity.
- Implemented and independently reviewed global process exclusion, residual-process
  detection/termination accounting and frozen methodology, before live can be enabled.
- Authorized, bounded future live execution if desired; none ran for this repair.
- Genuine run-bound blind human assessments under the five frozen dimensions.
- An explicitly agreed numerical aggregation/promotion rule if a numerical winner
  is required. Until then there is no score or winner.

Unintegrated handoff dependency: `src/valuation_engine/ai/quarter_package.py` is
absent, while the handoff service imported `build_package`. The full canonical
service was restored; no replacement `PITQuarterPackageV1` implementation or
manifest guarantee was fabricated. The handoff documentation also references
`run_codex_pilot_v6.py`; it is absent and is not part of these candidate tools.
