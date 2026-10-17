#!/usr/bin/env python3
"""Bounded Method C candidate research for a seven-quarter historical panel.

Default dry-run makes zero provider calls, creates no output, and never opens a
formal or historical candidate database. Each execution is a fresh, isolated
quarter using the S2 version-2 provenance schema. There is no seed, resume,
automatic retry, panel-wide live loop, quality verdict, or promotion pathway.
Live execution is blocked until frozen methodology and global single-process /
no-residual-provider isolation are implemented and reviewed. Reserved opt-in
flags cannot unlock it; a fresh output directory is not a global process lock.
"""

import argparse
import sys
from importlib import import_module
from pathlib import Path

# Direct script execution and importlib-based offline tests share the same helper.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    s2 = import_module("run_fsi_s2_experiment")
else:
    s2 = import_module(".run_fsi_s2_experiment", __package__)

PANEL_QUARTERS = (
    "FY2023-Q2",
    "FY2023-Q3",
    "FY2024-Q1",
    "FY2024-Q2",
    "FY2025-Q4",
    "FY2026-Q1",
    "FY2027-Q2",
)
MAX_CALLS_PER_QUARTER = s2.MAX_CALLS_PER_METHOD
LEGACY_SEED_ERROR = (
    "Legacy S2 seeding is disabled: historical evidence lacks complete run-bound "
    "source/call provenance. Historical databases are left untouched. Supply verified "
    "source bytes and prepared context for a fresh candidate run instead."
)


def seed_fy2023_q2_if_needed(cohort_db_path):
    """Fail closed for legacy callers without opening either source or destination."""
    raise ValueError(LEGACY_SEED_ERROR)


def check_preflight(quarter, prepared=None, source_contents=None):
    """Validate explicit inputs only; no database discovery, provider, or filesystem writes."""
    if quarter not in PANEL_QUARTERS:
        raise ValueError(f"Quarter {quarter!r} is not in the allowed seven-quarter panel")
    if (prepared is None) != (source_contents is None):
        raise ValueError("Prepared context and source bytes must be supplied together")
    result = {
        "quarter": quarter,
        "preflight_status": "UNVERIFIED_MISSING_INPUTS",
        "live_api_calls_made": 0,
        "max_calls_per_quarter": MAX_CALLS_PER_QUARTER,
        "max_total_calls": MAX_CALLS_PER_QUARTER,
        "live_authorization": "NOT_GRANTED",
        "live_execution": "BLOCKED",
        "live_block_reason": s2.LIVE_BLOCK_REASON,
        "source_authenticity_and_pit_metadata": "UNVERIFIED",
        "quality_verdict": "UNSCORED",
        "promotion_ready": False,
    }
    if prepared is not None:
        result["context_hash"] = s2.verify_prepared(prepared, source_contents, quarter)
        result["preflight_status"] = "INPUT_BYTES_AND_BLOCKS_VERIFIED"
        result["chunks_planned"] = len(list(s2.chunks(prepared["sources"]["blocks"])))
        result["maximum_planned_calls"] = result["chunks_planned"] + 2
    return result


def run_dry_run(quarter, prepared=None, source_contents=None):
    """Inspect one candidate research plan without importing a live provider."""
    return {
        "mode": "DRY_RUN",
        "timestamp": s2.now(),
        "target_quarter": quarter,
        "research_status": "CANDIDATE_RESEARCH_ONLY",
        "preflight": check_preflight(quarter, prepared, source_contents),
        "method_c": s2.build_method_payloads(quarter)["method_c"],
        "live_api_calls_made": 0,
        "quality_verdict": "UNSCORED",
        "promotion_ready": False,
    }


def run_quarter(
    quarter,
    *,
    provider,
    prepared,
    source_contents,
    output_dir,
    execution_mode,
    authorize_live=False,
    model=None,
):
    """Persist a complete new Method C run; never reopen or reuse a previous candidate.

    Synthetic tests must explicitly select OFFLINE_SYNTHETIC. LIVE_EXECUTION
    always fails before input access, provider checks, or filesystem writes.
    Authorization and model arguments are reserved and cannot unlock live work.
    The shared runner accounts for every attempt and performs no outer retries.
    """
    if execution_mode not in {"OFFLINE_SYNTHETIC", "LIVE_EXECUTION"}:
        raise ValueError("Explicit execution mode required")
    if execution_mode == "LIVE_EXECUTION":
        raise ValueError(s2.LIVE_BLOCK_REASON)
    check_preflight(quarter, prepared, source_contents)
    if prepared is None:
        raise ValueError("Execution requires prepared context and verified source bytes")
    # Refuse overwrite and evidence reuse. This is only per-output isolation;
    # it does not implement global process exclusion or residual-process checks.
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    candidate = output_dir / "candidate.db"
    s2.init_candidate_database(candidate)
    summary = s2.run_single_method(
        "method_c",
        s2.build_method_payloads(quarter)["method_c"],
        provider,
        prepared,
        candidate,
        source_contents=source_contents,
        execution_mode=execution_mode,
    )
    result = {
        "mode": execution_mode,
        "target_quarter": quarter,
        "research_status": "CANDIDATE_RESEARCH_ONLY",
        "max_total_calls": MAX_CALLS_PER_QUARTER,
        "method_c": summary,
        "quality_verdict": "UNSCORED",
        "promotion_ready": False,
    }
    with (output_dir / f"{quarter}_receipt.json").open("x", encoding="utf-8") as receipt:
        receipt.write(s2.encode(result) + "\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quarter", choices=PANEL_QUARTERS, default="FY2023-Q3")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--live", action="store_true", help="Reserved; live execution is blocked")
    parser.add_argument("--authorize-live", action="store_true")
    parser.add_argument("--model", help="Explicit provider model; no inferred default")
    parser.add_argument("--prepared-context", type=Path)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, help="New directory for this quarter only")
    parser.add_argument(
        "--seed-q2", action="store_true", help="Unsupported legacy import; always refused"
    )
    args = parser.parse_args(argv)
    if args.seed_q2:
        parser.error(LEGACY_SEED_ERROR)
    if args.live and not (
        args.authorize_live
        and args.model
        and args.model.strip()
        and args.prepared_context
        and args.source_dir
        and args.output_dir
    ):
        parser.error(
            "Live mode requires --authorize-live, --model, --prepared-context, "
            "--source-dir and a fresh --output-dir"
        )
    if args.live:
        parser.error(s2.LIVE_BLOCK_REASON)
    if bool(args.prepared_context) != bool(args.source_dir):
        parser.error("Both --prepared-context and --source-dir are required")
    prepared, contents = None, None
    if args.prepared_context:
        prepared, contents = s2.load_inputs(args.prepared_context, args.source_dir)
    print(s2.encode(run_dry_run(args.quarter, prepared, contents)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
