# StockOS M4.1 Codex V5 Recovery Execution Report

Date: 2026-09-24  
Status: In progress; no new model execution has been authorized by the recovery gates.

## P0: Baseline and in-flight state

- Repository: `/Users/eason/Documents/Coding/StockOS`, branch `main`, HEAD `22e9b9ee944408cb67d5217ca66dd880498fb440`.
- The existing M4.1 working-tree changes were preserved. The baseline captured 31 changed files, their content hashes, and the tracked diff hash `52ca19cc8c8ce90f2f2e3907e5d421d232c1524b07f2a91ec40c2f53d054384e` in `data/m41/codex/attempts/20260924T091619Z-p0-d7ce3de8/`.
- A read-only SQLite query found the latest committed Codex Q2 run was run 13, `PromptSetV4`, with 22 provider calls and one snapshot. The V5 completion receipt was absent at capture time.
- Process inspection returned `Operation not permitted`. The reviewed name-only process query did not return a result and was canceled. This is not evidence that no process is running.
- `data/m41/codex/attempts/active.lock` records the unresolved legacy V5 process state. New Codex attempts stop while this lock exists.

## P1: Changes made

- Added an append-only attempt journal with UTC/random attempt IDs, changed-file hashes, durable progress events, and an atomic singleton lock.
- Instrumented Codex CLI attempts with `launch_requested`, `runner_started`, `provider_check_requested`, `provider_checked`, `inference_started`, `stage_completed`, and `finished` events. Logs keep stdout/stderr hashes and allowlisted error types; they do not store raw stderr or environment values.
- If termination cannot be confirmed, the journal marks the process state unknown, preserves the lock, and prevents the service from retrying or starting another Codex stage.
- Tightened the persisted isolation receipt gate to require exactly C1–C12, all PASS, the current policy/model binding, no historical data in the isolation experiment, and matching before/after configuration hashes.
- Added `scripts/probe_codex_pit_launch.py` for a single synthetic response with no historical input.
- Updated the V5 pilot to save attempt-specific context, provider-check, preservation, progress, and pilot receipts. The validation runner now requires the exact pilot receipt path and writes its outputs into its own attempt directory.

## Current gate

The code changes and probe entry point are present in the working tree, but no tests, synthetic model call, Q2 run, or quarter expansion has been executed in this turn. The recovery plan requires an interpretable process-state check before any new model request; that check remains unavailable. No P1 execution PASS is claimed.

Before continuing, verify whether a prior `run_codex_pilot_v5.py`, `run_codex_validation_v5.py`, `probe_codex_pit_launch.py`, or `codex exec` process is still active. Only after confirming none is active should the legacy lock be resolved and the synthetic probe run. A probe PASS is still not Q2 acceptance.
