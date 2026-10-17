#!/usr/bin/env python3
"""Read-only full admission replay for v2 candidate lineage, never research quality.

Exit 1 indicates inconsistent lineage; 2 means consistent engineering records with
unresolved human/model/authenticity proof. Legacy candidates remain unverified.
"""

import argparse
import importlib.util
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def load_runner():
    path = Path(__file__).with_name("run_fsi_s2_experiment.py")
    spec = importlib.util.spec_from_file_location("s2_lineage_runner", path)
    if spec is None or spec.loader is None:
        raise ImportError("S2 replay runner is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replay(runner, prepared, config, calls, check, prefix):
    """Replay every draft in order, including duplicate and rejected candidates."""
    evidence: dict[str, dict[str, Any]] = {}
    features: dict[str, dict[str, Any]] = {}
    challenges: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    expected: dict[str, list[dict[str, Any]]] = {
        name: [] for name in ("s2_evidence", "s2_features", "s2_challenges", "s2_guard_rejections")
    }
    batches = list(runner.chunks(prepared["sources"]["blocks"]))
    extract_index = 0
    check(
        prefix + "complete_stages",
        [call["stage"] for call in calls]
        == ["extract"] * len(batches) + ["synthesize", "challenge"],
    )

    def reject(stage, kind, reason, draft, call_id):
        rejections.append({"stage": stage, "claim_type": kind, "reason": reason, "raw": draft})
        expected["s2_guard_rejections"].append(
            {
                "stage": stage,
                "claim_type": kind,
                "reason": reason,
                "raw_json": runner.encode(draft),
                "call_id": call_id,
            }
        )

    for call in calls:
        stage, call_id = call["stage"], call["id"]
        if stage == "extract":
            batch = batches[extract_index]
            payload = {"cutoff": prepared["quant_context"]["information_cutoff"], "blocks": batch}
            schema = runner.Extraction
        elif stage == "synthesize":
            payload, schema = {"evidence": list(evidence.values())}, runner.Synthesis
        elif stage == "challenge":
            payload = {
                "evidence": list(evidence.values()),
                "quant_context": prepared["quant_context"],
                "features": features,
            }
            schema = runner.Challenges
        else:
            raise ValueError("Unknown call stage")
        exact = json.loads(call["exact_request"])
        check(
            prefix + f"call_{call_id}.request",
            exact == runner.method_prompt(stage, payload, schema, config)
            and runner.digest([stage, exact]) == call["request_hash"],
        )
        raw = json.loads(call["raw_response"])
        metadata = raw.get("execution_metadata", {})
        check(
            prefix + f"call_{call_id}.response",
            runner.digest(raw) == call["response_hash"]
            and call["status"] == "completed"
            and metadata.get("provider_execution_status") == "completed"
            and raw.get("response_model") == call["actual_model"]
            and metadata.get("input_tokens") == call["tokens_in"]
            and metadata.get("output_tokens") == call["tokens_out"]
            and call["error_type"] is None,
        )
        parsed = schema.model_validate(raw["structured_output"])
        if stage == "extract":
            block_map = {block["block_id"]: block for block in batch}
            for draft in parsed.evidence:
                valid, reason = runner.validate_evidence(draft, block_map)
                if draft.speaker is not None and draft.speaker != block_map.get(
                    draft.block_id, {}
                ).get("speaker"):
                    valid, reason = None, "unsupported_speaker"
                key = f"{extract_index}:{draft.key}"
                if key in evidence:
                    valid, reason = None, "duplicate_evidence_key"
                if valid is None:
                    reject(stage, "evidence", reason, draft.model_dump(), call_id)
                    continue
                valid["key"] = key
                evidence[key] = valid
                expected["s2_evidence"].append(
                    {
                        "evidence_key": key,
                        "call_id": call_id,
                        "draft_key": draft.key,
                        "metadata_json": runner.encode(valid),
                        **{
                            field: valid[field]
                            for field in (
                                "source_document_id",
                                "source_hash",
                                "block_id",
                                "span_hash",
                                "topic",
                                "span",
                                "implication",
                                "certainty",
                                "statement_type",
                            )
                        },
                    }
                )
            extract_index += 1
        elif stage == "synthesize":
            for draft in parsed.features:
                valid, reason = runner.admit_feature(draft, evidence)
                if draft.feature_name in features:
                    valid, reason = None, "duplicate_feature"
                if valid is not None:
                    reason = runner.guard_g_invariant(valid, evidence)
                    if reason:
                        valid = None
                if valid is None:
                    reject(stage, "feature", reason, draft.model_dump(), call_id)
                    continue
                features[draft.feature_name] = valid
                expected["s2_features"].append(
                    {
                        "call_id": call_id,
                        "metadata_json": runner.encode(valid),
                        "status": "ADMITTED",
                        "rationale": valid["net_assessment"],
                        "supporting_keys": runner.encode(valid["supporting_evidence"]),
                        "contradicting_keys": runner.encode(valid["contradicting_evidence"]),
                        **{
                            field: valid[field]
                            for field in (
                                "feature_name",
                                "feature_value",
                                "direction",
                                "confidence",
                                "evidence_count",
                            )
                        },
                    }
                )
        else:
            for draft in parsed.challenges:
                reason = None
                if (
                    not draft.evidence
                    or any(key not in evidence for key in draft.evidence)
                    or not runner.safe_narrative(draft.description)
                ):
                    reason = "unsupported_challenge"
                elif (
                    draft.kind == "anomaly"
                    and draft.anomaly_code not in prepared["quant_context"]["anomaly_codes"]
                ):
                    reason = "unknown_quant_anomaly"
                elif (draft.kind == "regime") != (draft.affected_model_variable == "regime"):
                    reason = "inconsistent_regime_target"
                if reason:
                    reject(stage, "challenge", reason, draft.model_dump(), call_id)
                    continue
                valid = {
                    **draft.model_dump(),
                    "confidence": runner.confidence([evidence[key] for key in draft.evidence]),
                }
                challenges.append(valid)
                expected["s2_challenges"].append(
                    {
                        "call_id": call_id,
                        "metadata_json": runner.encode(valid),
                        "status": "ADMITTED",
                        "evidence_keys": runner.encode(draft.evidence),
                        "target_variable": draft.affected_model_variable,
                        **{
                            field: valid[field]
                            for field in ("kind", "description", "direction", "confidence")
                        },
                    }
                )
    return expected, evidence, features, challenges, rejections


def verify(database, run_ids):
    runner = load_runner()
    checks: list[dict[str, Any]] = []
    result = {
        "scope": "complete-run admission replay; incomplete execution remains unverified",
        "format_version": 2,
        "checks": checks,
        "quality_verdict": "UNSCORED",
        "actual_model_identity": "UNVERIFIED",
        "source_authenticity_and_pit_metadata": "UNVERIFIED",
        "comparison_design_status": "UNVERIFIED_FROZEN_BASELINE_MISSING",
        "winner": None,
        "promotion_ready": False,
    }

    def check(name, condition):
        checks.append({"check": name, "status": "PASS" if condition else "FAIL"})

    try:
        path = Path(database).resolve(strict=True)
        if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
            raise ValueError("Obtain a consistent database snapshot without SQLite sidecars")
        before = runner.compute_sha256(path.read_bytes())
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            if conn.execute("PRAGMA user_version").fetchone()[0] != 2:
                raise ValueError("Legacy or unknown schema; cannot establish v2 lineage")
            if (
                not run_ids
                or len(run_ids) != len(set(run_ids))
                or any(type(i) is not int for i in run_ids)
            ):
                raise ValueError("Select distinct explicit run IDs")
            check("sqlite_quick_check", conn.execute("PRAGMA quick_check").fetchone()[0] == "ok")
            for run_id in run_ids:
                prefix = f"run_{run_id}."
                run = conn.execute(
                    "SELECT * FROM s2_experiment_runs WHERE id=?", (run_id,)
                ).fetchone()
                if run is None:
                    raise ValueError("Selected run is missing")
                prepared, config, summary = (
                    json.loads(run[field])
                    for field in ("context_json", "config_json", "receipt_json")
                )
                method = run["method"]
                if run["status"] != "COMPLETED":
                    count = conn.execute(
                        "SELECT count(*) FROM s2_provider_calls WHERE run_id=?", (run_id,)
                    ).fetchone()[0]
                    check(
                        prefix + "incomplete_attempt_accounting", count == run["calls_made"] <= 22
                    )
                    checks.append(
                        {
                            "check": prefix + "execution_complete",
                            "status": "UNVERIFIED",
                            "run_status": run["status"],
                        }
                    )
                    continue
                check(
                    prefix + "configuration",
                    config
                    == runner.build_method_payloads(run["quarter"])["method_" + method.lower()]
                    and config["prompt_version"] == run["prompt_version"]
                    and config["guard_version"] == run["guard_version"],
                )
                docs = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM s2_source_documents WHERE run_id=?", (run_id,)
                    )
                ]
                # Hash EVERY stored BLOB before mapping duplicate content hashes.
                check(
                    prefix + "all_source_bytes",
                    all(
                        runner.compute_sha256(doc["content"]) == doc["source_hash"] for doc in docs
                    ),
                )
                contents = {doc["source_hash"]: doc["content"] for doc in docs}
                context_hash = runner.verify_prepared(prepared, contents, run["quarter"])
                check(
                    prefix + "context_hash",
                    context_hash == run["context_hash"] == summary["context_hash"],
                )
                expected_docs = {
                    doc["source_document_id"]: doc for doc in prepared["sources"]["documents"]
                }
                check(
                    prefix + "source_documents",
                    len(docs) == len(expected_docs)
                    and all(
                        json.loads(doc["metadata_json"])
                        == expected_docs.get(doc["source_document_id"])
                        and doc["source_hash"]
                        == expected_docs[doc["source_document_id"]]["source_hash"]
                        for doc in docs
                    ),
                )
                stored_blocks = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM s2_source_blocks WHERE run_id=?", (run_id,)
                    )
                ]
                blocks = {row["block_id"]: json.loads(row["block_json"]) for row in stored_blocks}
                check(
                    prefix + "source_blocks",
                    len(stored_blocks) == len(blocks)
                    and blocks
                    == {block["block_id"]: block for block in prepared["sources"]["blocks"]},
                )
                tables = (
                    "s2_provider_calls",
                    "s2_evidence",
                    "s2_features",
                    "s2_challenges",
                    "s2_guard_rejections",
                )
                rows = {
                    table: [
                        dict(row)
                        for row in conn.execute(
                            f"SELECT * FROM {table} WHERE run_id=? ORDER BY id", (run_id,)
                        )
                    ]
                    for table in tables
                }
                check(
                    prefix + "row_identity",
                    all(row["method"] == method for group in rows.values() for row in group),
                )
                calls = rows["s2_provider_calls"]
                check(
                    prefix + "call_budget",
                    0 < len(calls) <= 22
                    and len(calls) == run["calls_made"] == summary["calls_made"],
                )
                expected, evidence, features, challenges, rejections = replay(
                    runner, prepared, config, calls, check, prefix
                )
                for table, values in expected.items():
                    actual = rows[table]
                    matches = len(values) == len(actual) and all(
                        all(actual_row[key] == value for key, value in expected_row.items())
                        for actual_row, expected_row in zip(actual, values, strict=True)
                    )
                    check(prefix + table + ".complete_admission_replay", matches)
                check(
                    prefix + "receipt",
                    summary["run_id"] == run_id
                    and summary["method"] == method
                    and summary["quarter"] == run["quarter"]
                    and summary["status"] == run["status"] == "COMPLETED"
                    and summary["features"] == features
                    and summary["challenges"] == challenges
                    and summary["rejections"] == rejections
                    and summary["evidence_count"] == len(evidence)
                    and summary["admitted_features_count"] == len(features)
                    and summary["challenges_count"] == len(challenges)
                    and summary["rejections_count"] == len(rejections)
                    and summary["format_version"] == 2
                    and summary["failure_type"] is None
                    and summary["started_at"] == run["created_at"]
                    and summary["actual_model_identity"] == "UNVERIFIED"
                    and summary["source_authenticity_and_pit_metadata"] == "UNVERIFIED"
                    and summary["quality_verdict"] == "UNSCORED"
                    and summary["promotion_ready"] is False
                    and summary["execution_mode"] == "OFFLINE_SYNTHETIC"
                    and summary["comparison_design_status"] == config["comparison_design_status"],
                )
                check(
                    prefix + "required_outputs",
                    bool(features)
                    and {"upside", "downside", "regime"} <= {item["kind"] for item in challenges},
                )
        check("inputs_unchanged", before == runner.compute_sha256(path.read_bytes()))
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        sqlite3.Error,
    ) as error:
        checks.append(
            {
                "check": "input_or_lineage_error",
                "status": "FAIL",
                "error_type": type(error).__name__,
            }
        )
    result["lineage_status"] = (
        "INCONSISTENT"
        if any(check["status"] == "FAIL" for check in checks)
        else "UNVERIFIED"
        if any(check["status"] == "UNVERIFIED" for check in checks)
        else "CONSISTENT"
    )
    result["status"] = (
        "INCONSISTENT" if result["lineage_status"] == "INCONSISTENT" else "UNVERIFIED"
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-id", type=int, action="append", required=True)
    args = parser.parse_args(argv)
    result = verify(args.database, args.run_id)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 1 if result["status"] == "INCONSISTENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
