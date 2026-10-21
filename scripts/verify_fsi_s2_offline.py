#!/usr/bin/env python3
"""Check existing S2 artifacts without importing or executing the live runner.

Only stdlib, immutable read-only SQLite, and input-file reads are used. JSON goes
to stdout; this program never creates an output file or a source database.
Exit 1 means inconsistent/malformed evidence, 2 means unresolved proof, 0 means
all implemented checks passed. This legacy format cannot establish source
lineage, actual model identity, semantic quality, or promotion readiness.
"""

import argparse
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

TABLES = {
    "s2_experiment_runs": "id method quarter calls_made status receipt_json",
    "s2_provider_calls": "run_id method stage status actual_model raw_response",
    "s2_evidence": "run_id method evidence_key topic span implication",
    "s2_features": (
        "run_id method feature_name feature_value confidence rationale "
        "supporting_keys contradicting_keys evidence_count status"
    ),
    "s2_challenges": "run_id method kind target_variable direction description confidence status",
    "s2_guard_rejections": "run_id method reason",
}
METRICS = {
    "calls_made": "API 總調用數",
    "evidence_count": "抽取事實數",
    "admitted_features_count": "准入特徵數",
    "rejections_count": "Guard G 違規沒收",
    "challenges_count": "模型挑戰數",
}


def load_json(text):
    def invalid_constant(value):
        raise ValueError(f"Non-finite JSON constant: {value}")

    return json.loads(text, parse_constant=invalid_constant)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def readonly_connection(path):
    """Refuse missing DBs and SQLite sidecars; never recover/change a journal."""
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError("Database is not a regular file")
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("SQLite sidecar present; obtain a separate consistent snapshot first")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    return connection


def key_list(value):
    keys = load_json(value)
    if not isinstance(keys, list) or any(not isinstance(k, str) or not k for k in keys):
        raise ValueError("Evidence references must be a list of nonempty strings")
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate evidence references")
    return keys


def feature_errors(features, evidence):
    """Mechanical stored-evidence checks only; these do not prove quotation fidelity."""
    errors = Counter()
    index = {}
    for item in evidence:
        key = item["evidence_key"]
        if key in index:
            errors["duplicate_evidence_key"] += 1
        index[key] = item
    for feature in features:
        confidence = feature["confidence"]
        if (
            not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            errors["invalid_confidence"] += 1
        try:
            support = key_list(feature["supporting_keys"])
            counter = key_list(feature["contradicting_keys"])
        except (ValueError, TypeError):
            errors["malformed_evidence_keys"] += 1
            continue
        if set(support) & set(counter):
            errors["evidence_role_overlap"] += 1
        keys = support + counter
        if feature["evidence_count"] != len(keys):
            errors["evidence_count_mismatch"] += 1
        if any(key not in index for key in keys):
            errors["evidence_not_bound_to_run"] += 1
            continue
        if any(index[key]["topic"] != feature["feature_name"] for key in keys):
            errors["evidence_topic_mismatch"] += 1
        value = feature["feature_value"]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            errors["invalid_feature_value"] += 1
        elif value:
            if not support:
                errors["final_support_empty"] += 1
            expected = "positive" if value > 0 else "negative"
            if not any(index[key]["implication"] == expected for key in support):
                errors["direction_unsupported"] += 1
    return dict(errors)


def report_metrics(text):
    result = {}
    for key, label in METRICS.items():
        rows = [line.split("|") for line in text.splitlines() if label in line and "|" in line]
        if len(rows) != 1:
            raise ValueError(f"Missing or ambiguous report metric: {key}")
        values = []
        for cell in rows[0][2:4]:
            match = re.fullmatch(r"\s*(\d+)\s*[^\d|]*", cell)
            if match is None:
                raise ValueError(f"Malformed report metric: {key}")
            values.append(int(match[1]))
        if len(values) != 2:
            raise ValueError(f"Missing report method column: {key}")
        result[key] = values
    return result


def verify(database, receipt_path, report_path):
    checks = []

    def record(name, status, **details):
        checks.append({"check": name, "status": status, **details})

    def compare(name, condition, **details):
        record(name, "PASS" if condition else "FAIL", **details)

    result = {
        "scope": "legacy S2 artifact consistency and mechanical guards only",
        "quality_verdict": "NOT_VERIFIED",
        "promotion_ready": False,
        "checks": checks,
    }
    try:
        inputs = {
            "database": Path(database),
            "receipt": Path(receipt_path),
            "report": Path(report_path),
        }
        result["input_sha256"] = {key: sha256(path) for key, path in inputs.items()}
        receipt = load_json(inputs["receipt"].read_text(encoding="utf-8"))
        metrics = report_metrics(inputs["report"].read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("mode") != "LIVE_EXECUTION":
            raise ValueError("A LIVE_EXECUTION receipt is required; a dry-run is not evidence")
        quarter = receipt.get("quarter")
        if quarter != "FY2023-Q2":
            raise ValueError("This verifier supports the frozen FY2023-Q2 S2 experiment only")
        with closing(readonly_connection(inputs["database"])) as connection:
            missing = {}
            for table, required in TABLES.items():
                columns = {r["name"] for r in connection.execute(f"PRAGMA table_info({table})")}
                absent = sorted(set(required.split()) - columns)
                if absent:
                    missing[table] = absent
            compare("schema", not missing, missing=missing)
            if missing:
                raise ValueError("Incomplete S2 schema")
            compare(
                "sqlite_quick_check",
                [r[0] for r in connection.execute("PRAGMA quick_check")] == ["ok"],
            )
            inventory = []
            for row in connection.execute(
                "SELECT r.id, r.method, r.status, r.calls_made, count(c.rowid) AS persisted_calls "
                "FROM s2_experiment_runs r LEFT JOIN s2_provider_calls c ON c.run_id=r.id "
                "WHERE r.quarter=? GROUP BY r.id ORDER BY r.id",
                (quarter,),
            ):
                inventory.append(dict(row))
            result["run_inventory"] = inventory
            selected = set()
            for offset, method in enumerate(("B", "C")):
                summary = receipt.get("method_" + method.lower())
                if not isinstance(summary, dict) or type(summary.get("run_id")) is not int:
                    raise ValueError(f"Missing explicit {method} run identity")
                run_id = summary["run_id"]
                selected.add(run_id)
                run = connection.execute(
                    "SELECT * FROM s2_experiment_runs WHERE id=?", (run_id,)
                ).fetchone()
                if run is None:
                    raise ValueError(f"Selected {method} run does not exist")
                compare(
                    f"{method}.run_identity",
                    run["method"] == summary.get("method") == method
                    and run["quarter"] == quarter
                    and run["status"] == "COMPLETED",
                )
                compare(f"{method}.stored_receipt", load_json(run["receipt_json"]) == summary)
                rows = {}
                for table in TABLES:
                    if table != "s2_experiment_runs":
                        rows[table] = [
                            dict(r)
                            for r in connection.execute(
                                f"SELECT * FROM {table} WHERE run_id=?", (run_id,)
                            )
                        ]
                compare(
                    f"{method}.row_identity",
                    all(r["method"] == method for group in rows.values() for r in group),
                )
                calls = rows["s2_provider_calls"]
                evidence = rows["s2_evidence"]
                features = [r for r in rows["s2_features"] if r["status"] == "ADMITTED"]
                challenges = [r for r in rows["s2_challenges"] if r["status"] == "ADMITTED"]
                observed = dict(
                    zip(
                        METRICS,
                        (
                            len(calls),
                            len(evidence),
                            len(features),
                            len(rows["s2_guard_rejections"]),
                            len(challenges),
                        ),
                        strict=True,
                    )
                )
                for metric, count in observed.items():
                    expected = summary.get(metric)
                    compare(
                        f"{method}.receipt.{metric}",
                        type(expected) is int and count == expected,
                        observed=count,
                        receipt=expected,
                    )
                    compare(
                        f"{method}.report.{metric}",
                        count == metrics[metric][offset],
                        observed=count,
                        report=metrics[metric][offset],
                    )
                compare(
                    f"{method}.call_cap",
                    type(run["calls_made"]) is int
                    and run["calls_made"] == len(calls)
                    and 0 < len(calls) <= 22,
                )
                compare(
                    f"{method}.call_status",
                    bool(calls) and all(r["status"] == "completed" for r in calls),
                )
                compare(
                    f"{method}.required_stages",
                    {"synthesize", "challenge"} <= {r["stage"] for r in calls},
                )
                compare(
                    f"{method}.raw_responses_retained",
                    bool(calls)
                    and all(
                        isinstance(r["raw_response"], str) and r["raw_response"].strip()
                        for r in calls
                    ),
                )
                errors = feature_errors(features, evidence)
                compare(f"{method}.mechanical_guard", bool(features) and not errors, errors=errors)
                expected_features = summary.get("features")
                if not isinstance(expected_features, dict):
                    raise ValueError("Receipt features must be a mapping")
                payload_matches = len(features) == len(expected_features) and {
                    f["feature_name"] for f in features
                } == set(expected_features)
                for feature in features:
                    expected = expected_features.get(feature["feature_name"], {})
                    if not isinstance(expected, dict):
                        raise ValueError("Receipt feature must be an object")
                    payload_matches &= all(
                        feature[field] == expected.get(field)
                        for field in ("feature_value", "confidence")
                    )
                    payload_matches &= feature["rationale"] == expected.get("net_assessment")
                    try:
                        payload_matches &= key_list(feature["supporting_keys"]) == expected.get(
                            "supporting_evidence"
                        )
                        payload_matches &= key_list(feature["contradicting_keys"]) == expected.get(
                            "contradicting_evidence"
                        )
                    except (ValueError, TypeError):
                        payload_matches = False
                compare(f"{method}.feature_payload", payload_matches)
                expected_challenges = summary.get("challenges")
                expected_rejections = summary.get("rejections")
                if not isinstance(expected_challenges, list) or not all(
                    isinstance(c, dict) for c in expected_challenges
                ):
                    raise ValueError("Receipt challenges must be a list of objects")
                if not isinstance(expected_rejections, list):
                    raise ValueError("Receipt rejections must be a list")
                persisted_challenges = Counter(
                    (
                        c["kind"],
                        c["target_variable"],
                        c["direction"],
                        c["description"],
                        c["confidence"],
                    )
                    for c in challenges
                )
                receipt_challenges = Counter(
                    (
                        c.get("kind", "anomaly"),
                        c.get("affected_model_variable", "revenue"),
                        c.get("direction", "down"),
                        c.get("description", ""),
                        c.get("confidence"),
                    )
                    for c in expected_challenges
                )
                compare(f"{method}.challenge_payload", persisted_challenges == receipt_challenges)
                compare(
                    f"{method}.receipt_list_counts",
                    len(expected_challenges) == summary.get("challenges_count")
                    and len(expected_rejections) == summary.get("rejections_count"),
                )
                record(
                    f"{method}.actual_model_identity",
                    "UNVERIFIED",
                    observed_labels=sorted({str(r["actual_model"]) for r in calls}),
                    reason="Saved labels are not independent model identity attestation",
                )
            unselected = sum(
                row["persisted_calls"] for row in inventory if row["id"] not in selected
            )
            result["persisted_call_total"] = sum(row["persisted_calls"] for row in inventory)
            record(
                "experiment_budget_scope",
                "UNVERIFIED",
                unselected_calls=unselected,
                reason="No immutable experiment/attempt lineage binds historical calls and retries to the reported pair",
            )
        for name, reason in (
            (
                "source_fidelity",
                "No source-package hash or source-block lineage in this legacy evidence schema",
            ),
            (
                "request_and_admission_lineage",
                "Full requests and stage admission cannot be reconstructed from legacy rows",
            ),
            (
                "semantic_quality",
                "Counts and narrative length cannot establish rubric quality or a method winner",
            ),
            (
                "historical_formal_db_preservation",
                "This verifier has no authenticated before/after formal DB snapshot",
            ),
        ):
            record(name, "UNVERIFIED", reason=reason)
        compare(
            "inputs_unchanged",
            result["input_sha256"] == {key: sha256(path) for key, path in inputs.items()},
        )
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as error:
        record("input_or_schema_error", "FAIL", reason=str(error))
    result["status"] = (
        "INCONSISTENT" if any(c["status"] == "FAIL" for c in checks) else "UNVERIFIED"
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    result = verify(args.database, args.receipt, args.report)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 1 if result["status"] == "INCONSISTENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
