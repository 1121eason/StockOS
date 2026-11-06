"""Synthetic tests: no live runner imports, original DBs, or provider calls."""

import importlib.util
import json
import socket
import sqlite3
import subprocess
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/verify_fsi_s2_offline.py"
SPEC = importlib.util.spec_from_file_location("fsi_s2_offline_verifier", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network and subprocess calls are forbidden in offline verifier tests")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)


@pytest.fixture
def artifacts(tmp_path):
    database = tmp_path / "candidate.db"
    receipt_path = tmp_path / "receipt.json"
    report_path = tmp_path / "report.md"
    receipt = {"mode": "LIVE_EXECUTION", "quarter": "FY2023-Q2"}
    with sqlite3.connect(database) as connection:
        for table, fields in verifier.TABLES.items():
            columns = []
            for field in fields.split():
                kind = (
                    "INTEGER"
                    if field in {"id", "run_id", "calls_made", "evidence_count"}
                    else "TEXT"
                )
                if field in {"feature_value", "confidence"}:
                    kind = "REAL"
                columns.append(field + " " + kind)
            connection.execute(f"CREATE TABLE {table} ({','.join(columns)})")
        for run_id, method in enumerate(("B", "C"), 1):
            feature = {
                "feature_name": "demand_momentum",
                "feature_value": -0.3,
                "confidence": 0.5,
                "net_assessment": "Demand weakened",
                "supporting_evidence": ["e1"],
                "contradicting_evidence": [],
            }
            challenge = {
                "kind": "anomaly",
                "affected_model_variable": "revenue",
                "direction": "down",
                "description": "Check demand sensitivity",
                "confidence": 0.5,
            }
            summary = {
                "run_id": run_id,
                "method": method,
                "calls_made": 2,
                "evidence_count": 1,
                "admitted_features_count": 1,
                "rejections_count": 0,
                "challenges_count": 1,
                "features": {"demand_momentum": feature},
                "rejections": [],
                "challenges": [challenge],
            }
            receipt["method_" + method.lower()] = summary
            connection.execute(
                "INSERT INTO s2_experiment_runs VALUES (?,?,?,?,?,?)",
                (run_id, method, "FY2023-Q2", 2, "COMPLETED", json.dumps(summary)),
            )
            for stage in ("synthesize", "challenge"):
                connection.execute(
                    "INSERT INTO s2_provider_calls VALUES (?,?,?,?,?,?)",
                    (run_id, method, stage, "completed", "unavailable", "{}"),
                )
            connection.execute(
                "INSERT INTO s2_evidence VALUES (?,?,?,?,?,?)",
                (run_id, method, "e1", "demand_momentum", "Demand weakened", "negative"),
            )
            connection.execute(
                "INSERT INTO s2_features VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    method,
                    "demand_momentum",
                    -0.3,
                    0.5,
                    "Demand weakened",
                    '["e1"]',
                    "[]",
                    1,
                    "ADMITTED",
                ),
            )
            connection.execute(
                "INSERT INTO s2_challenges VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    method,
                    "anomaly",
                    "revenue",
                    "down",
                    "Check demand sensitivity",
                    0.5,
                    "ADMITTED",
                ),
            )
    receipt_path.write_text(json.dumps(receipt))
    report_path.write_text(
        "\n".join(
            f"| **{label}** | {value} 個 | {value} 個 |"
            for label, value in zip(verifier.METRICS.values(), (2, 1, 1, 0, 1), strict=True)
        )
        + "\nMETHOD_C_SUPERIOR"
    )
    return database, receipt_path, report_path


def checks(result):
    return {item["check"]: item for item in result["checks"]}


def test_consistent_counts_never_become_quality_or_promotion_pass(artifacts):
    before = {path: verifier.sha256(path) for path in artifacts}
    result = verifier.verify(*artifacts)
    assert result["status"] == "UNVERIFIED"
    assert result["quality_verdict"] == "NOT_VERIFIED"
    assert result["promotion_ready"] is False
    assert not any(c["status"] == "FAIL" for c in result["checks"])
    assert checks(result)["B.actual_model_identity"]["status"] == "UNVERIFIED"
    assert checks(result)["semantic_quality"]["status"] == "UNVERIFIED"
    assert before == {path: verifier.sha256(path) for path in artifacts}
    assert not list(artifacts[0].parent.glob("candidate.db-*"))


def test_missing_database_is_not_created(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        verifier.readonly_connection(missing)
    assert not missing.exists()


@pytest.mark.parametrize("sidecar", ["-wal", "-shm", "-journal"])
def test_sidecar_is_refused_without_recovery(artifacts, sidecar):
    database = artifacts[0]
    sidecar_path = Path(str(database) + sidecar)
    sidecar_path.write_bytes(b"preserved")
    before = verifier.sha256(database)
    result = verifier.verify(*artifacts)
    assert result["status"] == "INCONSISTENT"
    assert "sidecar" in checks(result)["input_or_schema_error"]["reason"]
    assert verifier.sha256(database) == before
    assert sidecar_path.read_bytes() == b"preserved"


def test_readonly_connection_rejects_writes(artifacts):
    connection = verifier.readonly_connection(artifacts[0])
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM s2_evidence")
    finally:
        connection.close()


@pytest.mark.parametrize(
    "mutation,check",
    [
        ("UPDATE s2_evidence SET run_id=99 WHERE method='B'", "B.receipt.evidence_count"),
        ("UPDATE s2_features SET supporting_keys='{}' WHERE method='B'", "B.mechanical_guard"),
        (
            "UPDATE s2_features SET contradicting_keys='[\"e1\"]' WHERE method='B'",
            "B.mechanical_guard",
        ),
        ("UPDATE s2_evidence SET implication='mixed' WHERE method='B'", "B.mechanical_guard"),
        ("UPDATE s2_evidence SET topic='other_topic' WHERE method='B'", "B.mechanical_guard"),
        ("UPDATE s2_features SET rationale='replaced' WHERE method='B'", "B.feature_payload"),
        ("UPDATE s2_challenges SET description='replaced' WHERE method='B'", "B.challenge_payload"),
        (
            "UPDATE s2_provider_calls SET raw_response=NULL WHERE method='B'",
            "B.raw_responses_retained",
        ),
        ("UPDATE s2_provider_calls SET status='timeout' WHERE method='B'", "B.call_status"),
        ("UPDATE s2_provider_calls SET method='C' WHERE run_id=1", "B.row_identity"),
        ("DROP TABLE s2_guard_rejections", "schema"),
    ],
)
def test_corrupted_evidence_fails_closed(artifacts, mutation, check):
    with sqlite3.connect(artifacts[0]) as connection:
        connection.execute(mutation)
    result = verifier.verify(*artifacts)
    assert result["status"] == "INCONSISTENT"
    assert checks(result)[check]["status"] == "FAIL"


def test_report_counter_disagrees_with_database(artifacts):
    report = artifacts[2]
    report.write_text(report.read_text().replace("| 2 個 | 2 個 |", "| 99 個 | 2 個 |"))
    assert checks(verifier.verify(*artifacts))["B.report.calls_made"]["status"] == "FAIL"


def test_receipt_is_bound_to_stored_run(artifacts):
    receipt = json.loads(artifacts[1].read_text())
    receipt["method_b"]["calls_made"] = 5
    artifacts[1].write_text(json.dumps(receipt))
    result = verifier.verify(*artifacts)
    assert checks(result)["B.stored_receipt"]["status"] == "FAIL"
    assert checks(result)["B.receipt.calls_made"]["status"] == "FAIL"


def test_old_calls_are_inventoried_and_not_hidden(artifacts):
    with sqlite3.connect(artifacts[0]) as connection:
        connection.execute(
            "INSERT INTO s2_experiment_runs VALUES (99,'B','FY2023-Q2',1,'RUNNING','{}')"
        )
        connection.execute(
            "INSERT INTO s2_provider_calls VALUES (99,'B','synthesize','timeout',NULL,NULL)"
        )
    result = verifier.verify(*artifacts)
    assert result["persisted_call_total"] == 5
    assert checks(result)["experiment_budget_scope"]["unselected_calls"] == 1
    assert result["promotion_ready"] is False


@pytest.mark.parametrize("content", ['{"mode":"DRY_RUN"}', "[]", '{"mode":NaN}'])
def test_invalid_or_dry_run_receipt_is_not_evidence(artifacts, content):
    artifacts[1].write_text(content)
    assert verifier.verify(*artifacts)["status"] == "INCONSISTENT"


def test_cli_returns_nonzero_and_creates_no_output(artifacts, capsys):
    before = sorted(p.name for p in artifacts[0].parent.iterdir())
    code = verifier.main(
        [
            "--database",
            str(artifacts[0]),
            "--receipt",
            str(artifacts[1]),
            "--report",
            str(artifacts[2]),
        ]
    )
    assert code == 2
    assert json.loads(capsys.readouterr().out)["promotion_ready"] is False
    assert sorted(p.name for p in artifacts[0].parent.iterdir()) == before
