# FSI W1 offline preparation

This uncommitted addition is based on `0d71b713d64deccfbf1f77614dbea4bed8d63fe1`.
The user approved D01–D03 for offline W1 only. Live model calls, formal database
writes, commits, pushes and deployment are not part of this delivery.

`valuation_engine.ai.fsi_w1` freezes the prospective B/C system text, shared
tasks and schemas, 22/44 attempt caps, and the approved blind-review rules. It
does not change the formal V1 service or historical V6 results. Its protocol and
source-package validators compare canonical JSON, including numeric/boolean
types, and reject modified content even if the caller supplies a new hash.

`scripts/prepare_fsi_w1.py` takes an explicit database, source directory and run
ID. It opens only `mode=ro&immutable=1`, rejects SQLite sidecars, verifies exact
run/company/source/cutoff bindings, and reparses the complete selected SEC/IR
bytes with the canonical narrative parser. It does not follow historical raw
paths or import a provider. The default writes nothing and prints preflight JSON:

```sh
PYTHONPATH=src python scripts/prepare_fsi_w1.py \
  --database /absolute/private/qve.db \
  --raw-dir /absolute/private/raw \
  --run-id 15
```

An explicit `--output-dir /absolute/private/NEW-directory` exports protocol,
package and provenance/preflight JSON. Existing directories are refused. These
files can contain private research inputs; keep them outside public source
delivery. Unknown publication times remain null. Timestamp evidence links and
cached evidence bytes are checked where present, but their historical claims
are not independently authenticated. All authenticity/model/quality flags
remain unverified or unscored, with formal decisions withheld.

All selected documents and narrative blocks are retained. An input requiring
more than 22 attempts per method returns `BLOCKED_CALL_CAP`; it is not truncated
and no cap is increased. Every plan keeps live execution blocked regardless of
whether its input fits the budget. Future changes to chunking, scope or caps
require a new approved protocol, rather than a silent adjustment.

`fsi_runtime.OfflineLease` provides exclusive lock creation and explicit
owner-bound completion for offline fault testing. `shared_offline_lease` uses
one fixed lock within the supplied shared state root, independent of run or
quarter. Exceptions, unknown residual state and replacement locks are retained.
Process observations preserve raw text, hashes and parsed identities; malformed,
failed or altered observations fail closed and provider-like parent/desktop
processes have no implicit exemptions. The optional native collector is read-only
and was not executed in W1. Executable-name classification does not establish
that interpreter-wrapped or custom providers are absent. Observation authenticity,
reviewed classification, native isolation and actual residual-process verification
remain unresolved. No process is terminated and live execution stays blocked.

Offline verification uses only synthetic bytes and temporary SQLite databases:

```sh
PYTHONPATH=src python -B scripts/validate_fsi_w1_offline.py \
  --evidence-dir /absolute/NEW-empty-existing-evidence-directory
```

The controller installs Python audit restrictions before collecting tests,
blocking network and child-process creation and allowing SQLite only in the
test temporary root (or in memory). It removes the PostgreSQL test URL from that
process and records the exact selected test paths, environment, JUnit and audit
counts. This is affected-path synthetic verification, not a full-suite,
PostgreSQL, native sandbox, live model, semantic-quality or promotion certificate.

Research review tooling is not activated by freezing the rubric. There are no
human scores or winner in this delivery. Further provider identity, native
isolation, human review and candidate-to-approval contracts remain separate
acceptance gates.
