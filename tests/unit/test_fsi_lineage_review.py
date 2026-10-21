"""Adversarial lineage checks against synthetic, temporary S2 records only."""

import copy
import importlib.util
import json
import socket
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlparse

import pytest

SUPPORT_PATH = Path(__file__).with_name("test_fsi_s2_provenance.py")
SPEC = importlib.util.spec_from_file_location("fsi_lineage_synthetic_support", SUPPORT_PATH)
assert SPEC is not None and SPEC.loader is not None
support = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(support)
package = support.package


@pytest.fixture(autouse=True)
def isolated_offline_test(monkeypatch, tmp_path):
    """Forbid transport and any database outside the current test directory."""

    def forbidden(*args, **kwargs):
        raise AssertionError("External calls are forbidden in lineage review tests")

    connect = sqlite3.connect

    def only_temporary_database(database, *args, **kwargs):
        value = str(database)
        path = Path(unquote(urlparse(value).path) if value.startswith("file:") else value)
        assert path.resolve().is_relative_to(tmp_path.resolve()), "Non-temporary DB access"
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(sqlite3, "connect", only_temporary_database)


def test_attempt_is_committed_and_counted_before_provider_execution(tmp_path, package):
    database = tmp_path / "candidate.db"
    provider = support.SyntheticProvider()
    original_request = provider.request
    observed_stages = []

    def inspect_committed_attempt(stage, exact):
        with sqlite3.connect(database) as conn:
            attempt = conn.execute(
                "SELECT stage,status,exact_request,raw_response FROM s2_provider_calls ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert attempt == (stage, "pending", support.runner.encode(exact), None)
            count = conn.execute("SELECT calls_made FROM s2_experiment_runs").fetchone()[0]
            assert count == len(observed_stages) + 1
            assert count == conn.execute("SELECT count(*) FROM s2_provider_calls").fetchone()[0]
        observed_stages.append(stage)
        return original_request(stage, exact)

    provider.request = inspect_committed_attempt
    summary, _ = support.run(tmp_path, package, provider, database=database)
    assert summary["status"] == "COMPLETED", summary
    assert observed_stages == ["extract", "synthesize", "challenge"]


@pytest.mark.parametrize("duplicate_stage", ["extract", "synthesize"])
def test_first_admission_and_later_duplicate_rejection_replays_consistently(
    tmp_path, package, duplicate_stage
):
    def transform(stage, raw):
        if stage == duplicate_stage:
            field = "evidence" if stage == "extract" else "features"
            values = raw["structured_output"][field]
            values.append(copy.deepcopy(values[0]))
        return raw

    summary, database = support.run(tmp_path, package, support.SyntheticProvider(transform))
    assert summary["status"] == "COMPLETED"
    assert summary["rejections_count"] == 1
    assert summary["rejections"][0]["reason"] == (
        "duplicate_evidence_key" if duplicate_stage == "extract" else "duplicate_feature"
    )
    result = support.verifier.verify(database, [summary["run_id"]])
    assert result["lineage_status"] == "CONSISTENT", result
    assert result["status"] == "UNVERIFIED"


@pytest.mark.parametrize(
    "mutation",
    [
        "call_id=999",
        "reason='fabricated reason'",
        "raw_json='{}'",
        "stage='challenge'",
        "claim_type='challenge'",
    ],
)
def test_rejection_must_match_its_exact_response_and_call(tmp_path, package, mutation):
    def transform(stage, raw):
        if stage == "extract":
            invalid = copy.deepcopy(raw["structured_output"]["evidence"][0])
            invalid.update(key="rejected", span="This quote was invented for a test.")
            raw["structured_output"]["evidence"].append(invalid)
        return raw

    summary, database = support.run(tmp_path, package, support.SyntheticProvider(transform))
    assert summary["status"] == "COMPLETED"
    assert summary["rejections_count"] == 1
    assert support.verifier.verify(database, [summary["run_id"]])["lineage_status"] == "CONSISTENT"
    with sqlite3.connect(database) as conn:
        conn.execute(f"UPDATE s2_guard_rejections SET {mutation}")
    result = support.verifier.verify(database, [summary["run_id"]])
    assert result["lineage_status"] == "INCONSISTENT", result


def test_admissible_response_challenge_cannot_disappear_from_rows_and_receipt(tmp_path, package):
    def transform(stage, raw):
        if stage == "challenge":
            extra = copy.deepcopy(raw["structured_output"]["challenges"][0])
            extra["description"] = "Further demand remains possible."
            raw["structured_output"]["challenges"].append(extra)
        return raw

    summary, database = support.run(tmp_path, package, support.SyntheticProvider(transform))
    assert summary["status"] == "COMPLETED"
    assert summary["challenges_count"] == 4
    summary["challenges"].pop()
    summary["challenges_count"] -= 1
    with sqlite3.connect(database) as conn:
        conn.execute("DELETE FROM s2_challenges WHERE id=(SELECT max(id) FROM s2_challenges)")
        conn.execute(
            "UPDATE s2_experiment_runs SET receipt_json=? WHERE id=?",
            (json.dumps(summary), summary["run_id"]),
        )
    result = support.verifier.verify(database, [summary["run_id"]])
    assert result["lineage_status"] == "INCONSISTENT", result


def test_every_source_blob_is_hashed_even_when_document_rows_share_a_hash(tmp_path, package):
    prepared, contents = copy.deepcopy(package)
    original = prepared["sources"]["documents"][0]
    duplicate = {**original, "source_document_id": original["source_document_id"] + 1}
    prepared["sources"]["documents"].append(duplicate)
    derived, _ = support.runner.source_blocks(
        SimpleNamespace(
            id=duplicate["source_document_id"],
            content_hash=duplicate["source_hash"],
            document_type=duplicate["document_type"],
        ),
        contents[duplicate["source_hash"]],
    )
    prepared["sources"]["blocks"].extend(
        {
            **block,
            **{field: duplicate[field] for field in ("tier", "published_at", "available_at")},
        }
        for block in derived
    )
    summary, database = support.run(tmp_path, (prepared, contents))
    assert summary["status"] == "COMPLETED"
    assert support.verifier.verify(database, [summary["run_id"]])["lineage_status"] == "CONSISTENT"
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE s2_source_documents SET content=X'00' WHERE source_document_id=?",
            (original["source_document_id"],),
        )
    result = support.verifier.verify(database, [summary["run_id"]])
    assert result["lineage_status"] == "INCONSISTENT", result


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual_model_identity", "VERIFIED"),
        ("source_authenticity_and_pit_metadata", "VERIFIED"),
        ("quality_verdict", "SCORED"),
        ("promotion_ready", True),
        ("format_version", 1),
        ("failure_type", "RuntimeError"),
        ("started_at", "2000-01-01T00:00:00+00:00"),
        ("execution_mode", "LIVE_EXECUTION"),
        ("method", "C"),
        ("comparison_design_status", "VERIFIED"),
    ],
)
def test_receipt_cannot_relabel_synthetic_origin_or_override_unverified_flags(
    tmp_path, package, field, value
):
    summary, database = support.run(tmp_path, package)
    summary[field] = value
    with sqlite3.connect(database) as conn:
        conn.execute(
            "UPDATE s2_experiment_runs SET receipt_json=? WHERE id=?",
            (json.dumps(summary), summary["run_id"]),
        )
    result = support.verifier.verify(database, [summary["run_id"]])
    assert result["lineage_status"] == "INCONSISTENT", result


@pytest.mark.parametrize(
    "table", ["s2_provider_calls", "s2_evidence", "s2_features", "s2_challenges"]
)
def test_rows_cannot_claim_a_different_method_than_their_run(tmp_path, package, table):
    summary, database = support.run(tmp_path, package)
    with sqlite3.connect(database) as conn:
        conn.execute(f"UPDATE {table} SET method='C' WHERE run_id=?", (summary["run_id"],))
    result = support.verifier.verify(database, [summary["run_id"]])
    assert result["lineage_status"] == "INCONSISTENT", result


def test_evidence_cannot_borrow_an_actual_call_from_another_run(tmp_path, package):
    first, database = support.run(tmp_path, package)
    second, _ = support.run(tmp_path, package, database=database)
    with sqlite3.connect(database) as conn:
        borrowed = conn.execute(
            "SELECT id FROM s2_provider_calls WHERE run_id=? AND stage='extract'",
            (second["run_id"],),
        ).fetchone()[0]
        conn.execute("UPDATE s2_evidence SET call_id=? WHERE run_id=?", (borrowed, first["run_id"]))
    result = support.verifier.verify(database, [first["run_id"], second["run_id"]])
    assert result["lineage_status"] == "INCONSISTENT", result
