"""Cohort safety tests use only synthetic source bytes and temporary databases."""

import builtins
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

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts/run_fsi_cohort_expansion.py"
SPEC = importlib.util.spec_from_file_location("fsi_cohort_safety_runner", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
cohort = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cohort)

SPAN = "Demand momentum improved as customers adopted the new architecture."
QUARTER = "FY2023-Q3"


@pytest.fixture(autouse=True)
def isolated_offline_test(monkeypatch, tmp_path):
    """Block transport and any SQLite access outside this test's temporary directory."""

    def forbidden(*args, **kwargs):
        raise AssertionError("External calls are forbidden in cohort safety tests")

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
    monkeypatch.chdir(tmp_path)


def make_inputs(quarter=QUARTER, block_count=1, large=False):
    padding = " Additional synthetic context." * 700 if large else ""
    paragraphs = "".join(
        f"<p>{SPAN} Synthetic paragraph {index}.{padding}</p>" for index in range(block_count)
    )
    content = f'<html><body><div class="article-body">{paragraphs}</div></body></html>'.encode()
    sha = cohort.s2.compute_sha256(content)
    source = SimpleNamespace(id=7, content_hash=sha, document_type="Earnings Release")
    blocks, _ = cohort.s2.source_blocks(source, content)
    metadata = {
        "source_document_id": 7,
        "source_hash": sha,
        "document_type": "Earnings Release",
        "source_url": "https://example.invalid/synthetic-source",
        "published_at": "2022-01-01T00:00:00+00:00",
        "available_at": "2022-01-01T00:00:00+00:00",
        "tier": 1,
        "block_count": len(blocks),
        "timestamp_precision": "synthetic_fixture",
        "availability_evidence_id": None,
    }
    prepared = {
        "quant_context": {
            "quarter": quarter,
            "information_cutoff": "2027-01-01T00:00:00+00:00",
            "anomaly_codes": [],
        },
        "sources": {
            "documents": [metadata],
            "blocks": [
                {
                    **block,
                    **{key: metadata[key] for key in ("published_at", "available_at", "tier")},
                }
                for block in blocks
            ],
        },
    }
    return prepared, {sha: content}


class SyntheticProvider:
    """In-memory deterministic adapter; no provider or subprocess is invoked."""

    def __init__(self, model="synthetic-model", failure=None):
        self.model_name = model
        self.failure = failure
        self.calls = []
        self.checks = 0

    def check(self):
        self.checks += 1
        return {"ready": True}

    def request(self, stage, exact):
        self.calls.append((stage, copy.deepcopy(exact)))
        if self.failure == "exception":
            raise TimeoutError("Synthetic timeout")
        if self.failure == "quota":
            return {"execution_metadata": {"provider_execution_status": "quota_limited"}}
        if self.failure == "invalid_schema":
            structured = {"evidence": [{"key": "incomplete"}]}
        elif stage == "extract":
            structured = {
                "evidence": [
                    {
                        "key": "e1",
                        "block_id": exact["untrusted_data"]["blocks"][0]["block_id"],
                        "span": SPAN,
                        "speaker": None,
                        "topic": "demand_momentum",
                        "implication": "positive",
                        "certainty": "explicit",
                        "statement_type": "reported_fact",
                    }
                ]
            }
        elif stage == "synthesize":
            structured = {
                "features": [
                    {
                        "feature_name": "demand_momentum",
                        "feature_value": 0.3,
                        "time_horizon": "current_quarter",
                        "supporting_evidence": ["0:e1"],
                        "contradicting_evidence": [],
                        "net_assessment": "Demand momentum improved with customer adoption.",
                    }
                ],
                "sections": [],
            }
        else:
            structured = {
                "challenges": [
                    {
                        "kind": kind,
                        "description": "Check demand sensitivity against customer adoption.",
                        "direction": "monitor",
                        "affected_model_variable": "regime" if kind == "regime" else "revenue",
                        "time_horizon": "current_quarter",
                        "evidence": ["0:e1"],
                        "anomaly_code": None,
                    }
                    for kind in ("upside", "downside", "regime")
                ]
            }
        return {
            "structured_output": structured,
            "response_model": self.model_name,
            "execution_metadata": {
                "provider_execution_status": "completed",
                "input_tokens": 11,
                "output_tokens": 13,
            },
        }


def execute(
    tmp_path,
    *,
    quarter=QUARTER,
    provider=None,
    prepared=None,
    contents=None,
    output_name="fresh",
    **kwargs,
):
    if prepared is None:
        prepared, contents = make_inputs(quarter)
    return cohort.run_quarter(
        quarter,
        provider=provider or SyntheticProvider(),
        prepared=prepared,
        source_contents=contents,
        output_dir=tmp_path / output_name,
        execution_mode="OFFLINE_SYNTHETIC",
        **kwargs,
    )


def test_default_dry_run_has_no_calls_no_db_and_missing_inputs_unverified(
    tmp_path, capsys, monkeypatch
):
    formal = tmp_path / "formal.db"
    formal.write_bytes(b"historical database must not be opened")
    monkeypatch.setenv("QVE_DATABASE_URL", f"sqlite:///{formal}")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert cohort.main(["--output-dir", str(tmp_path / "ignored")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "DRY_RUN"
    assert result["live_api_calls_made"] == 0
    assert result["preflight"]["preflight_status"] == "UNVERIFIED_MISSING_INPUTS"
    assert result["preflight"]["max_total_calls"] == 22
    assert result["quality_verdict"] == "UNSCORED"
    assert result["promotion_ready"] is False
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir()}


@pytest.mark.parametrize("quarter", cohort.PANEL_QUARTERS)
def test_all_panel_quarters_support_verified_readonly_preflight(quarter, tmp_path):
    prepared, contents = make_inputs(quarter)
    result = cohort.run_dry_run(quarter, prepared, contents)
    assert result["preflight"]["preflight_status"] == "INPUT_BYTES_AND_BLOCKS_VERIFIED"
    assert result["preflight"]["source_authenticity_and_pit_metadata"] == "UNVERIFIED"
    assert result["preflight"]["maximum_planned_calls"] == 3
    assert result["method_c"]["quarter"] == quarter
    assert list(tmp_path.iterdir()) == []


def test_disallowed_quarter_and_mismatched_context_rejected_before_output(tmp_path):
    with pytest.raises(ValueError, match="seven-quarter"):
        cohort.run_dry_run("FY2024-Q3")
    prepared, contents = make_inputs("FY2023-Q2")
    with pytest.raises(ValueError, match="quarter mismatch"):
        execute(tmp_path, prepared=prepared, contents=contents)
    assert list(tmp_path.iterdir()) == []


def test_legacy_seed_refused_without_reading_or_changing_historical_database(tmp_path, capsys):
    historical = tmp_path / "legacy.db"
    historical.write_bytes(b"preserve every historical byte")
    before = historical.read_bytes()
    with pytest.raises(ValueError, match="Legacy S2 seeding is disabled"):
        cohort.seed_fy2023_q2_if_needed(historical)
    with pytest.raises(SystemExit) as error:
        cohort.main(["--seed-q2"])
    assert error.value.code == 2
    assert "complete run-bound" in capsys.readouterr().err
    assert historical.read_bytes() == before
    assert list(tmp_path.iterdir()) == [historical]


@pytest.mark.parametrize(
    "missing",
    [
        "--authorize-live",
        "--model",
        "--prepared-context",
        "--source-dir",
        "--output-dir",
    ],
)
def test_live_cli_requires_each_explicit_gate_before_loading_inputs(tmp_path, missing):
    flags = {
        "--authorize-live": [],
        "--model": ["explicit-model"],
        "--prepared-context": [str(tmp_path / "absent.json")],
        "--source-dir": [str(tmp_path / "absent-sources")],
        "--output-dir": [str(tmp_path / "absent-output")],
    }
    argv = ["--live"]
    for flag, values in flags.items():
        if flag != missing:
            argv.extend([flag, *values])
    with pytest.raises(SystemExit) as error:
        cohort.main(argv)
    assert error.value.code == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("argv", [["--live", "--dry-run"], ["--resume"], ["--quarter", "all"]])
def test_conflicting_modes_panel_loops_and_resume_are_not_supported(argv):
    with pytest.raises(SystemExit) as error:
        cohort.main(argv)
    assert error.value.code == 2


def test_shared_input_loader_and_verified_dry_run_create_no_outputs(tmp_path, capsys):
    prepared, contents = make_inputs()
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps(prepared))
    sources = tmp_path / "sources"
    sources.mkdir()
    for sha, content in contents.items():
        (sources / sha).write_bytes(content)
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert (
        cohort.main(
            [
                "--prepared-context",
                str(context_path),
                "--source-dir",
                str(sources),
                "--output-dir",
                str(tmp_path / "ignored"),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["preflight"]["preflight_status"] == "INPUT_BYTES_AND_BLOCKS_VERIFIED"
    assert result["live_api_calls_made"] == 0
    assert before == sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))


def test_completed_synthetic_run_has_real_provenance_and_no_quality_claim(tmp_path):
    prepared, contents = make_inputs()
    provider = SyntheticProvider()
    result = execute(tmp_path, provider=provider, prepared=prepared, contents=contents)
    summary = result["method_c"]
    assert summary["status"] == "COMPLETED"
    assert summary["calls_made"] == len(provider.calls) == 3
    assert summary["evidence_count"] == summary["admitted_features_count"] == 1
    assert summary["challenges_count"] == 3
    assert summary["execution_mode"] == "OFFLINE_SYNTHETIC"
    assert result["research_status"] == "CANDIDATE_RESEARCH_ONLY"
    assert result["quality_verdict"] == summary["quality_verdict"] == "UNSCORED"
    assert result["promotion_ready"] is summary["promotion_ready"] is False
    assert provider.checks == 0
    database = tmp_path / "fresh" / "candidate.db"
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        evidence = dict(conn.execute("SELECT * FROM s2_evidence").fetchone())
        call = dict(
            conn.execute(
                "SELECT * FROM s2_provider_calls WHERE id=?", (evidence["call_id"],)
            ).fetchone()
        )
        document = dict(conn.execute("SELECT * FROM s2_source_documents").fetchone())
        run = dict(conn.execute("SELECT * FROM s2_experiment_runs").fetchone())
        assert evidence["run_id"] == call["run_id"] == document["run_id"] == run["id"]
        assert evidence["source_hash"] == cohort.s2.compute_sha256(document["content"])
        assert evidence["source_hash"] != cohort.s2.compute_sha256(evidence["topic"])
        assert evidence["block_id"] == prepared["sources"]["blocks"][0]["block_id"]
        assert evidence["span_hash"] == cohort.s2.compute_sha256(SPAN)
        assert evidence["source_document_id"] == 7
        exact = json.loads(call["exact_request"])
        assert call["request_hash"] == cohort.s2.digest(["extract", exact])
        assert json.loads(call["raw_response"])["structured_output"]["evidence"][0]["span"] == SPAN
        assert json.loads(run["receipt_json"]) == summary
    assert json.loads((tmp_path / "fresh" / f"{QUARTER}_receipt.json").read_text()) == result


@pytest.mark.parametrize("failure", ["exception", "quota", "invalid_schema"])
def test_failed_attempt_persisted_once_without_retry_resume_or_fabricated_counts(tmp_path, failure):
    provider = SyntheticProvider(failure=failure)
    result = execute(tmp_path, provider=provider)
    summary = result["method_c"]
    assert summary["status"] == "FAILED"
    assert summary["calls_made"] == len(provider.calls) == 1
    assert (
        summary["evidence_count"]
        == summary["admitted_features_count"]
        == summary["challenges_count"]
        == 0
    )
    database = tmp_path / "fresh" / "candidate.db"
    before = database.read_bytes()
    with sqlite3.connect(database) as conn:
        calls = conn.execute("SELECT status,error_type FROM s2_provider_calls").fetchall()
        assert len(calls) == 1
        assert calls[0][0] == "invalid_or_unavailable"
        assert calls[0][1]
    replacement = SyntheticProvider()
    with pytest.raises(FileExistsError):
        execute(tmp_path, provider=replacement)
    assert replacement.calls == []
    assert replacement.checks == 0
    assert database.read_bytes() == before


def test_existing_historical_output_is_not_opened_or_migrated(tmp_path):
    existing = tmp_path / "fresh"
    existing.mkdir()
    database = existing / "candidate.db"
    database.write_bytes(b"legacy schema intentionally not opened")
    with pytest.raises(FileExistsError):
        execute(tmp_path)
    assert database.read_bytes() == b"legacy schema intentionally not opened"
    assert list(existing.iterdir()) == [database]


@pytest.mark.parametrize(
    "mutation", ["source_bytes", "source_hash", "block_id", "span_text", "availability"]
)
def test_corrupted_source_provenance_is_rejected_before_execution(tmp_path, mutation):
    prepared, contents = make_inputs()
    if mutation == "source_bytes":
        contents[next(iter(contents))] = b"changed bytes"
    elif mutation == "source_hash":
        prepared["sources"]["blocks"][0]["source_hash"] = cohort.s2.compute_sha256(
            "demand_momentum"
        )
    elif mutation == "block_id":
        prepared["sources"]["blocks"][0]["block_id"] = "invented-evidence-key"
    elif mutation == "span_text":
        prepared["sources"]["blocks"][0]["text"] += " invented claim"
    else:
        prepared["sources"]["documents"][0]["available_at"] = "2030-01-01T00:00:00+00:00"
    provider = SyntheticProvider()
    with pytest.raises(ValueError):
        execute(tmp_path, provider=provider, prepared=prepared, contents=contents)
    assert provider.calls == []
    assert list(tmp_path.iterdir()) == []


def test_exact_maximum_is_twenty_extractions_plus_synthesis_and_challenge(tmp_path):
    prepared, contents = make_inputs(block_count=20, large=True)
    provider = SyntheticProvider()
    result = execute(tmp_path, provider=provider, prepared=prepared, contents=contents)
    assert result["method_c"]["status"] == "COMPLETED"
    assert result["method_c"]["calls_made"] == len(provider.calls) == 22
    assert sum(stage == "extract" for stage, _ in provider.calls) == 20


def test_over_budget_package_rejected_without_truncation_or_any_calls(tmp_path):
    prepared, contents = make_inputs(block_count=21, large=True)
    provider = SyntheticProvider()
    with pytest.raises(ValueError, match="call cap"):
        execute(tmp_path, provider=provider, prepared=prepared, contents=contents)
    assert provider.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "reserved_arguments",
    [
        {},
        {"authorize_live": True, "model": "different"},
        {"authorize_live": True, "model": "synthetic-model"},
    ],
)
def test_programmatic_live_is_blocked_even_with_authorization_and_model(
    tmp_path,
    monkeypatch,
    reserved_arguments,
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Blocked live path accessed inputs or output")

    provider = SyntheticProvider()
    monkeypatch.setattr(cohort, "check_preflight", forbidden)
    monkeypatch.setattr(cohort.s2, "init_candidate_database", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    with pytest.raises(ValueError) as error:
        cohort.run_quarter(
            QUARTER,
            provider=provider,
            prepared=None,
            source_contents=None,
            output_dir=tmp_path / "not-created",
            execution_mode="LIVE_EXECUTION",
            **reserved_arguments,
        )
    assert str(error.value) == cohort.s2.LIVE_BLOCK_REASON
    assert provider.calls == []
    assert provider.checks == 0
    assert list(tmp_path.iterdir()) == []


def test_all_live_cli_flags_cannot_unlock_input_provider_or_filesystem_access(
    tmp_path,
    monkeypatch,
    capsys,
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Blocked live path accessed input, provider, DB, or output")

    original_import = builtins.__import__

    def no_live_provider_import(name, *args, **kwargs):
        assert name != "valuation_engine.ai.cli_provider", "Live provider import is forbidden"
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_live_provider_import)
    monkeypatch.setattr(cohort.s2, "load_inputs", forbidden)
    monkeypatch.setattr(cohort.s2, "init_candidate_database", forbidden)
    monkeypatch.setattr(cohort, "check_preflight", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    with pytest.raises(SystemExit) as error:
        cohort.main(
            [
                "--live",
                "--authorize-live",
                "--model",
                "explicit-model",
                "--prepared-context",
                str(tmp_path / "absent.json"),
                "--source-dir",
                str(tmp_path / "absent-sources"),
                "--output-dir",
                str(tmp_path / "absent-output"),
            ]
        )
    assert error.value.code == 2
    assert cohort.s2.LIVE_BLOCK_REASON in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_omitted_blocks_cannot_shrink_the_verified_source_package(tmp_path):
    prepared, contents = make_inputs(block_count=2)
    prepared["sources"]["blocks"].pop()
    provider = SyntheticProvider()
    with pytest.raises(ValueError, match="omits parsed narrative blocks"):
        execute(tmp_path, provider=provider, prepared=prepared, contents=contents)
    assert provider.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("corruption", ["block", "span"])
def test_unbound_model_evidence_is_rejected_and_never_repaired(tmp_path, corruption):
    class UnboundEvidence(SyntheticProvider):
        def request(self, stage, exact):
            response = super().request(stage, exact)
            evidence = response["structured_output"]["evidence"][0]
            if corruption == "block":
                evidence["block_id"] = "invented-block"
            else:
                evidence["span"] = (
                    "This invented source claim was never present in the supplied document."
                )
            return response

    provider = UnboundEvidence()
    result = execute(tmp_path, provider=provider)
    assert result["method_c"]["status"] == "INCOMPLETE"
    assert result["method_c"]["evidence_count"] == 0
    assert result["method_c"]["rejections_count"] == 1
    assert result["method_c"]["calls_made"] == len(provider.calls) == 1
    with sqlite3.connect(tmp_path / "fresh" / "candidate.db") as conn:
        assert conn.execute("SELECT count(*) FROM s2_evidence").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM s2_guard_rejections").fetchone()[0] == 1


def test_new_output_starts_a_full_new_run_instead_of_reusing_evidence(tmp_path):
    first = SyntheticProvider()
    second = SyntheticProvider()
    execute(tmp_path, provider=first, output_name="first")
    before = (tmp_path / "first" / "candidate.db").read_bytes()
    result = execute(tmp_path, provider=second, output_name="second")
    assert result["method_c"]["calls_made"] == 3
    assert (
        [stage for stage, _ in first.calls]
        == [stage for stage, _ in second.calls]
        == [
            "extract",
            "synthesize",
            "challenge",
        ]
    )
    assert (tmp_path / "first" / "candidate.db").read_bytes() == before
