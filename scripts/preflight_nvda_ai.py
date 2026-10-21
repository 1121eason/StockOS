#!/usr/bin/env python3
"""Fresh native discovery and optional official-source capture; no model calls."""

import argparse
import json
from pathlib import Path

from valuation_engine.ai.native_preflight import (
    PACKAGE_HASH,
    capture_sources,
    collect_census,
    inspect_cli,
    inspect_preparation,
    load_bound,
    sha,
    summarize,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--capture-official-sources", action="store_true")
    args = parser.parse_args()
    # Validate all selected cached bytes before any network, CLI or output access.
    prepared, documents = inspect_preparation(args.preparation, args.raw_dir)
    args.output_dir.mkdir(parents=True, exist_ok=False)

    def save(name, value):
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")

    save("prepared.json", prepared)
    try:
        census = collect_census()
    except Exception as error:
        census = {
            "classification_status": "UNVERIFIED_COLLECTION_FAILED",
            "error_type": type(error).__name__,
        }
    save("process-census.json", census)
    try:
        cli = inspect_cli(args.executable)
    except Exception as error:
        cli = {"ready": False, "reason": "DISCOVERY_FAILED", "error_type": type(error).__name__}
    save("cli-discovery.json", cli)
    selected = load_bound(args.preparation / "package.json", "package_hash", PACKAGE_HASH)[
        "prepared"
    ]["sources"]["blocks"]
    sources = (
        capture_sources(documents, args.output_dir, selected)
        if args.capture_official_sources
        else []
    )
    save("sources.json", sources)
    receipt = summarize(prepared, cli, census, sources)
    receipt["audit_script_sha256"] = sha(Path(__file__).read_bytes())
    save("receipt.json", receipt)
    print(
        json.dumps(
            {
                k: receipt[k]
                for k in (
                    "quarter",
                    "ready_for_live",
                    "live_model_attempts",
                    "process_candidates",
                    "blockers",
                )
            }
        )
    )
    return 2  # Completed audit with unresolved acceptance gates; never a live PASS.


if __name__ == "__main__":
    raise SystemExit(main())
