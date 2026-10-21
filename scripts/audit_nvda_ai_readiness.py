#!/usr/bin/env python3
"""Read-only handoff audit; never imports/runs the W1 candidate or a provider."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(checkout: Path, evidence: Path) -> dict:
    manifest = json.loads((evidence / "source-manifest.json").read_text())
    protocol_path = evidence / "frozen-protocol.json"
    protocol = json.loads(protocol_path.read_text())
    protocol_hash = protocol.pop("protocol_hash")
    actual = hashlib.sha256(
        json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if actual != protocol_hash:
        raise ValueError("Frozen protocol content hash mismatch")
    verified = {}
    for relative, expected in manifest["files"].items():
        path = (checkout / relative).resolve()
        if not path.is_relative_to(checkout.resolve()) or sha(path) != expected:
            raise ValueError("Candidate source changed: " + relative)
        verified[relative] = expected
    prepared = json.loads((evidence / "source-preparation.json").read_text())
    if prepared["protocol_hash"] != protocol_hash:
        raise ValueError("Source preparation belongs to another protocol")
    quarters = [p for p in prepared["packages"] if p["quarter"] == "FY2023-Q2"]
    if len(quarters) != 1 or quarters[0]["plan"]["protocol_hash"] != protocol_hash:
        raise ValueError("Expected one protocol-bound Q2 source plan")
    plan, budget = quarters[0]["plan"], protocol["shared_budget"]
    within_cap = (
        plan["planned_attempts_per_method"] <= budget["attempts_per_method"]
        and plan["planned_attempts_per_pair"] <= budget["attempts_per_pair"]
    )
    return {
        "audit_version": "NVDAResearchSupplementReadinessV1",
        "audited_at": datetime.now(UTC).isoformat(),
        "quarter": "FY2023-Q2",
        "role": "research_supplement_only",
        "formal_policy_changed": False,
        "model_calls": 0,
        "formal_db_writes": 0,
        "protocol_hash": protocol_hash,
        "protocol_file_sha256": sha(protocol_path),
        "source_preparation_file_sha256": sha(evidence / "source-preparation.json"),
        "source_package_hash": quarters[0]["package_hash"],
        "candidate_source_files": verified,
        "review_rule": protocol["review_rule"],
        "versions": {
            "protocol": protocol["protocol_version"],
            "policy": protocol["policy_version"],
            "schema": protocol["schema_version"],
            "guard": protocol["guard_version"],
            "prompts": {k: v["prompt_version"] for k, v in protocol["methods"].items()},
        },
        "planned_attempts_per_method": plan["planned_attempts_per_method"],
        "planned_attempts_per_pair": plan["planned_attempts_per_pair"],
        "within_existing_single_pair_cap": within_cap,
        "gates": {
            "candidate_bytes_match_manifest": "PASS",
            "protocol_hash_binding": "PASS",
            "q2_planned_call_cap": "PASS" if within_cap else "BLOCKED",
            "source_authenticity_and_historical_timestamps": "NOT_REVALIDATED",
            "native_runtime_isolation_process_census_and_cleanup": "NOT_REVALIDATED",
            "exact_live_model_identity": "NOT_REVALIDATED",
            "new_exact_request_response_and_attempt_receipts": "NOT_RUN",
            "independent_human_blind_reviews_and_adjudication": "NOT_RUN",
        },
        "ready_for_live": False,
        "quality_verdict": "UNSCORED",
        "winner": None,
        "promotion_ready": False,
        "note": "Existing offline handoff audit only; not runtime validation, source refresh, call authorization, or AI quality approval.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--w1-checkout", type=Path, required=True)
    parser.add_argument("--w1-evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.w1_checkout, args.w1_evidence)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "quarter": result["quarter"],
                "ready_for_live": False,
                "verified_source_files": len(result["candidate_source_files"]),
                "within_existing_single_pair_cap": result["within_existing_single_pair_cap"],
            }
        )
    )


if __name__ == "__main__":
    main()
