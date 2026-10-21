# Typed internal policy provenance for current reconstruction

## Scope

Research bundle schema 2 adds one narrowly bounded source type for fixed WACC and terminal-growth policy artifacts. It does not change financial assumptions, DCF formulas, trading rules, formal database/pipeline approval, or vintage-verification requirements. Source records are importer assertions. No publication or historical availability is inferred from creation, effective, observation, or Git timestamps.

Schema 1 remains supported, strict and byte-compatible. Use schema 2 only when the distinction below is needed.

## Bundle contract

Schema 2 uses the schema-1 bundle fields plus required `economic_as_of`, a timezone-aware ISO timestamp. `as_of` is the current reconstruction cutoff; `economic_as_of` is the historical economic checkpoint and cannot exceed it. A historical economic checkpoint never certifies historical availability. All sources/inputs must satisfy the reconstruction cutoff. Each source requires `kind`:

- `external_document`: exactly the existing `id`, `url`, `published_at`, `retrieved_at`, `sha256` fields plus `kind`. The existing publication/availability/retrieval/URL/hash guards are unchanged.
- `internal_policy_artifact`: the exact fields below; no URL or publication timestamp is invented.

```json
{
  "kind": "internal_policy_artifact",
  "id": "internal_policy",
  "source_type": "fixed_research_policy_not_return_fitted",
  "policy_version": "SyntheticPolicyV1",
  "assumption_set_id": 1,
  "content_sha256": "<SHA-256 of compact canonical content JSON>",
  "assumption_content_hash": "<original assumption-set JSON SHA-256>",
  "content": {
    "version": "SyntheticPolicyV1",
    "classification": "research_reconstructed_internal",
    "effective_from": "2026-01-01T00:00:00Z",
    "wacc_base": "0.10",
    "terminal_growth_base": "0.02"
  },
  "created_at": "2026-01-02T00:00:00Z",
  "effective_from": "2026-01-01T00:00:00Z",
  "observed_at": "2026-01-03T00:00:00Z",
  "published_at": null,
  "historical_available_at": null,
  "source_reference": "Synthetic internal policy fixture; no public publication claimed",
  "parameter_records": [
    {"record_id": 11, "parameter": "wacc", "value": "0.10", "created_at": "2026-01-02T00:00:01Z"},
    {"record_id": 12, "parameter": "terminal_growth", "value": "0.02", "created_at": "2026-01-02T00:00:02Z"}
  ]
}
```

The example is synthetic and contains hash placeholders, so it is deliberately not an importable evidence record. All record IDs must be positive integers (not booleans). Parameter record IDs and names must be unique. Content must be a JSON object with at most 65,536 canonical characters. It can retain the complete original policy payload, but its version, classification, effective time, WACC and terminal-growth values must agree with the explicit record fields.

Two hashes preserve distinct identities:

1. `content_sha256`: SHA-256 of `json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)` encoded UTF-8.
2. `assumption_content_hash`: SHA-256 of `json.dumps(content, sort_keys=True, ensure_ascii=True, allow_nan=False)` encoded UTF-8, matching the repository's existing assumption-set default-separator convention. Do not substitute the compact hash for the original identity.

Both hashes are recomputed; neither authenticates the exporter or an excluded source database.

## Fail-closed policy boundary

- `published_at` and `historical_available_at` must remain JSON null for this internal type. Actual external publication, if present, belongs to the external-document contract.
- Artifact creation and effective timestamps must not exceed `observed_at`; parameter record creation must be between artifact creation and observation. Observation must not exceed the current reconstruction `as_of`.
- Current observation is the conservative source-availability boundary. Any policy input's `available_at` must be at or after observation and at or before reconstruction cutoff. It is not a historical publication claim.
- An internal artifact can support only `wacc` or `terminal_growth`, never cash, debt, shares or forecast cashflows, including null-valued inputs. An internally sourced rate must cite exactly that one artifact, be non-null, and equal its specific parameter record/content value.
- Internal source records must be used. External-only rate provenance remains allowed under the unchanged external rules.
- Attempts to import 2026 internal artifacts with 2022–2025 reconstruction cutoffs fail. Arbitrary flag fields cannot promote the evidence class.

Canonical DCF continues to compute unchanged values. Schema-2 results explicitly carry `historical_oos=false`, false source/model/price vintage-verification flags, the economic checkpoint, fixed limitations, `formal_decision=withheld`, and `source_verification=asserted_unverified`. The UI labels economic and reconstruction dates separately, shows both source kinds, and distinguishes creation/effective/current-observation timestamps from absent historical publication/availability.

## Storage and compatibility review

This is a **bundle-format extension**, not a SQLite migration. SQLite `user_version=1`, application ID, schema SQL, triggers, and workspace identity are unchanged. Run IDs retain `rw1_` plus the bundle-content hash; schema version and source payload are in that hash, so schema-1 and schema-2 identities cannot accidentally alias.

The new reader regenerates schema-1 result JSON exactly, without adding fields to old records. Existing schema-1 rows/results/digests remain valid and unchanged. Mixed schema-1/schema-2 stores are supported by the new reader and retain idempotency and immutable/integrity checks.

An **older executable cannot read schema-2 records** and will reject them rather than silently weaken validation. Use a separate research store for schema-2 rollout when an older UI/executable is still needed. Do not interpret unchanged SQLite version as backward executable compatibility with new JSON records. No automatic migration, rewriting, dropping or adoption of formal/unrelated databases occurs.

## Verification

Synthetic tests cover the two hashes, identity/value/date mismatches, malformed/extra fields, null-publication preservation, historical cutoff rejection, prohibited financial input citations, output forgery, immutable mixed-version replay, concurrency, and schema-1 result fingerprints. UI tests cover both kinds and XSS escaping. Private quarterly inputs and real-data acceptance evidence stay outside Git; no real input values, private source records or databases are needed in published tests.
