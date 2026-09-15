# Local research data

## Milestone 4 delivery

M4 data contains 26 prepared PIT contexts and coverage/validation receipts, not live AI results. Current AI snapshot count is zero. The human review set has 35 pending items. Extract m4-source and m4-review-data archives together, run `uv sync --locked`, then `uv run python scripts/prepare_m4.py` for offline context preparation. Real AI execution requires local provider settings; tests use isolated synthetic providers and must not be treated as historical analysis. Pre-M4 backups remain in the original workspace and are excluded from delivery.

## Milestone 3.1 delivery

Extract `quarterly-valuation-engine-m31-source.zip` and `nvda-m31-review-data.zip` together. Use `uv sync --locked`, then `uv run python scripts/run_m31.py --skip-preservation-audit`. Offline replay needs no SEC identity or downloads; dependencies require a cache or installation. Evidence lives in `data/m31/report/` and `data/m31/postgresql/`. The full request is `data/m31/received-request.txt`.

26 corrected snapshots under RegimePolicyV1.1 coexist with 52 immutable M3 rows. Four corrected transitions coexist with six prior implementation records. Never interpret whole-table totals as quarterly history. Pre-M3.1 SQLite/PG backups remain in the original workspace and are intentionally excluded from delivery; preservation receipts are included. The M3 conditional-pass issues below are historical context, resolved by the M3.1 report.

## Milestone 3 delivery

Extract `quarterly-valuation-engine-m3-source.zip` and `nvda-m3-review-data.zip` together, enter `quarterly-valuation-engine`, run `uv sync --locked`, then `uv run python scripts/run_m3.py --skip-preservation-audit`. The bundled local source archive supports offline replay without SEC identity or online financial data. Installing dependencies requires an existing cache or network. Original absolute source paths remain immutable provenance; missing paths fall back to the verified `data/raw/<hash>` files.

M3 evidence is in `data/m3/report/`; PostgreSQL receipts are in `data/m3/postgresql/`. The source/data bundle also retains M2 evidence. There are 26 final first-tradable regime observations, but 52 physical snapshot rows because immutable initial development records are preserved. The formal assumption payload includes `RegimeEngineV1.1-confidence-streak`; use the final report snapshot IDs, not an unfiltered table count. Three actual transitions in the final cohort correspond to six stored transition records across the two implementation cohorts.

`received-request.txt` preserves exactly what was received, including the mid-sentence truncation in section 22. The M3 report records the outstanding acceptance context and primary-state limitation. Pre-M3 backups and PostgreSQL server binaries are not packaged. `scripts/run_m3.py` repeats classifications and checks source bytes; original-workspace preservation checks require the retained pre-M3 backups. On a relocated bundle without those backups, the included preservation receipts remain the evidence; use the CLI for offline replay or use `--skip-preservation-audit` to repeat the full 26-quarter replay and source hash/idempotency checks without re-auditing absent backups.

## Milestone 2 delivery

Extract `quarterly-valuation-engine-m2-source.zip` and `nvda-m2-review-data.zip` into the same parent directory, then enter `quarterly-valuation-engine`. Run `uv sync --locked`, followed by `uv run python scripts/run_m2.py --repeat` for the frozen 26-quarter replay and financial evaluation. No online download or SEC identity is needed for the bundled replay. Methodology is in `docs/FORECAST_METHOD.md` and `docs/VALUATION_METHOD.md`; results are in `docs/MILESTONE_2_EXECUTION_REPORT.md` and `data/m2/report/`.

The formal typed-assumption cohort has 156 runs (26 quarters, two checkpoints, three models), 78 first-tradable valuations, and 339 realized financial evaluation records. SQLite retains 157 earlier immutable development runs as audit history; they are excluded from this cohort and accuracy evaluation. Database totals therefore exceed formal benchmark totals. PostgreSQL reports contain independently rebuilt and twice-replayed results; `backend-parity.json` compares numerical outputs. This M2 bundle includes live PostgreSQL evidence, not PostgreSQL server binaries or M1.1 dump archives. To repeat live validation, provision the isolated databases and use `scripts/validate_m2_postgres.py` with the documented local test setup.

Coverage is 26/26 forecasts and forward valuation, 24/26 DCF, and 13/26 Reverse DCF. Unavailable valid inputs remain NULL with provenance and reasons. Core and label migrations are `0005_research` and `0003_forecast_outcomes`. `scripts/audit_m2.py` is the original-workspace audit: it additionally requires the retained pre-M2 backups and the running PostgreSQL fixture; the resulting preservation/parity receipts are included in the bundle. It is not needed for offline replay. `scripts/report_m2.py` regenerates the report from bundled evidence after replay.

The preserved **M1.1 Final Closure** baseline is PM accepted. Its source/data bundles use the `m11-closure` filename suffix. Extract both into the same parent directory, enter `quarterly-valuation-engine`, then run `uv run python scripts/close_m11.py` for offline coverage or add `--live-sec` after configuring a valid SEC identity to execute two real downloads. M1.1 report: `docs/MILESTONE_1_1_FINAL_CLOSURE_REPORT.md`; evidence: `data/m11-closure/report/`. The earlier M1.1 reports, hashes and backups remain historical evidence and do not override the PM's accepted price/timestamp policy.

Everything in this directory except this README is ignored by Git. `raw/<sha256>` stores the exact downloaded bytes. `ir-manifest.json` maps each official URL, original retrieval instant and fiscal period to its hash/path. It supports offline replay with byte verification.

`qve.db`: current audited feature/source database. `labels.db`: separate outcome database. `exploratory-before-parser-review.db`: preserved first-pass database; not the authoritative output. It retains initial parser failures and interpretations for investigation.

JSON reports contain coverage, validation, snapshot/feature outputs, ingestion/idempotency counts and the latest-quarter manual check. They are local generated artifacts, not fabricated fixtures. Synthetic data exist only under `tests/` and temporary pytest databases.

For production, provision PostgreSQL feature and label databases separately and set the two URL environment variables. Never point both at the same database. Do not store SEC contact information in a source file or this directory.

For M1.1, extract both `quarterly-valuation-engine-m11-source.zip` and `nvda-m11-review-data.zip` into the same parent directory. Run commands from the resulting `quarterly-valuation-engine` directory. The exported databases retain their original source-file locations as immutable provenance; when those files are absent, the reader uses `QVE_RAW_DIR/<content_hash>` (default `data/raw`) and verifies the bytes against the stored hash. Do not alter database source paths after moving the archive.

Run `uv sync --locked`, then `uv run python scripts/harden_m11.py` to replay all bundled evidence offline. This uses the included databases, vendor response, manifests, timestamp sources and split documents. The full M1.1 report is `docs/MILESTONE_1_1_REPORT.md`; historical M1.1 reports are in `data/m11/report/`. Older root-level reports describe M1 and are not M1.1 acceptance results.

The historical M1.1 review bundle also includes actual PostgreSQL core/label dumps, schema, tests, backend parity and dump/restore verification. PostgreSQL core `qve_verified` was rebuilt from the real cache; it contains no original M1 snapshots. At that M1.1 checkpoint, the isolated PostgreSQL label database was empty. The SQLite label database retains the original 26 outcome labels.

Each archive contains a per-file hash manifest. `artifacts/m11-checksums.json` records the archive hashes. Credentials, caches and exploratory databases are excluded.
