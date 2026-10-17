"""Synthetic engineering fixtures only. No model quality or historical performance."""

import copy
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load("run_fsi_s2_experiment")
verifier = load("verify_fsi_lineage")


@pytest.fixture
def package():
    content = b"<html><body><p>Customer demand remained resilient while deployment timing depends on available capacity.</p></body></html>"
    sha = runner.compute_sha256(content)
    blocks, _ = runner.source_blocks(
        SimpleNamespace(id=101, content_hash=sha, document_type="SEC primary filing"), content
    )
    doc = {
        "source_document_id": 101,
        "source_hash": sha,
        "document_type": "SEC primary filing",
        "source_url": "https://example.test/synthetic-only",
        "tier": 1,
        "published_at": "2022-08-01T10:00:00+00:00",
        "available_at": "2022-08-01T10:00:00+00:00",
    }
    blocks = [
        {**block, **{field: doc[field] for field in ("tier", "published_at", "available_at")}}
        for block in blocks
    ]
    prepared = {
        "quant_context": {
            "quarter": "FY2023-Q2",
            "information_cutoff": "2022-08-02T10:00:00+00:00",
            "anomaly_codes": [],
        },
        "sources": {"documents": [doc], "blocks": blocks},
    }
    return prepared, {sha: content}


class SyntheticProvider:
    def __init__(self, transform=None):
        self.requests = []
        self.transform = transform

    def request(self, stage, exact):
        self.requests.append((stage, copy.deepcopy(exact)))
        if stage == "extract":
            block = exact["untrusted_data"]["blocks"][0]
            output = {
                "evidence": [
                    {
                        "key": "quote",
                        "block_id": block["block_id"],
                        "span": block["text"],
                        "speaker": None,
                        "topic": "demand_momentum",
                        "implication": "positive",
                        "certainty": "explicit",
                        "statement_type": "reported_fact",
                    }
                ]
            }
        elif stage == "synthesize":
            key = exact["untrusted_data"]["evidence"][0]["key"]
            output = {
                "features": [
                    {
                        "feature_name": "demand_momentum",
                        "feature_value": 0.5,
                        "time_horizon": "current_quarter",
                        "supporting_evidence": [key],
                        "contradicting_evidence": [],
                        "net_assessment": "Demand remains resilient.",
                    }
                ],
                "sections": [],
            }
        else:
            key = exact["untrusted_data"]["evidence"][0]["key"]
            output = {
                "challenges": [
                    {
                        "kind": kind,
                        "description": "Deployment remains conditional on capacity.",
                        "direction": "monitor",
                        "affected_model_variable": "regime" if kind == "regime" else "revenue",
                        "time_horizon": "current_quarter",
                        "evidence": [key],
                        "anomaly_code": None,
                    }
                    for kind in ("upside", "downside", "regime")
                ]
            }
        raw = {
            "response_model": "synthetic-fixture-only",
            "execution_metadata": {"provider_execution_status": "completed"},
            "structured_output": output,
        }
        return self.transform(stage, raw) if self.transform else raw


def run(tmp_path, package, provider=None, database=None, method="B"):
    database = database or tmp_path / "candidate.db"
    if not database.exists():
        runner.init_candidate_database(database)
    prepared, contents = package
    summary = runner.run_single_method(
        "method_" + method.lower(),
        runner.build_method_payloads("FY2023-Q2")["method_" + method.lower()],
        provider or SyntheticProvider(),
        prepared,
        database,
        source_contents=contents,
        execution_mode="OFFLINE_SYNTHETIC",
    )
    return summary, database


def test_exact_request_response_source_admission_lineage(tmp_path, package):
    provider = SyntheticProvider()
    summary, database = run(tmp_path, package, provider)
    assert summary["status"] == "COMPLETED", summary
    assert summary["execution_mode"] == "OFFLINE_SYNTHETIC"
    assert summary["quality_verdict"] == "UNSCORED"
    assert summary["calls_made"] == 3
    before = database.read_bytes()
    result = verifier.verify(database, [summary["run_id"]])
    assert result["lineage_status"] == "CONSISTENT", result
    assert result["status"] == "UNVERIFIED"
    assert result["winner"] is None and not result["promotion_ready"]
    assert database.read_bytes() == before
    with sqlite3.connect(database) as conn:
        calls = conn.execute(
            "SELECT stage,exact_request,request_hash,raw_response,response_hash,tokens_in FROM s2_provider_calls ORDER BY id"
        ).fetchall()
        for call, (stage, exact) in zip(calls, provider.requests, strict=True):
            assert json.loads(call[1]) == exact
            assert call[2] == runner.digest([stage, exact])
            assert call[4] == runner.digest(json.loads(call[3]))
            assert call[5] is None  # Missing provider usage is never fabricated as zero.
        evidence = conn.execute("SELECT source_hash,block_id,span_hash FROM s2_evidence").fetchone()
        assert evidence[0] == package[0]["sources"]["documents"][0]["source_hash"]
        assert evidence[1] == package[0]["sources"]["blocks"][0]["block_id"]


def test_no_evidence_reuse_across_same_method_runs(tmp_path, package):
    first, database = run(tmp_path, package)
    provider = SyntheticProvider()
    second, _ = run(tmp_path, package, provider, database)
    assert second["run_id"] != first["run_id"]
    assert [stage for stage, _ in provider.requests] == ["extract", "synthesize", "challenge"]
    assert (
        verifier.verify(database, [first["run_id"], second["run_id"]])["lineage_status"]
        == "CONSISTENT"
    )


def test_no_fixed_scores_winner_or_rationale_length_proxy(tmp_path, package):
    b, database = run(tmp_path, package)
    c, _ = run(tmp_path, package, database=database, method="C")
    result = runner.compare_and_evaluate(b, c)
    assert result["verdict"] == "UNSCORED" and result["winner"] is None
    assert result["method_b_baseline"]["score"] is None
    assert result["method_c_fsi"]["score"] is None
    assert set(result["rubric_assessment"].values()) == {"UNASSESSED_REQUIRES_HUMAN_BLIND_REVIEW"}
    b_prompt = runner.method_prompt(
        "extract", {}, runner.Extraction, runner.build_method_payloads("FY2023-Q2")["method_b"]
    )
    c_prompt = runner.method_prompt(
        "extract", {}, runner.Extraction, runner.build_method_payloads("FY2023-Q2")["method_c"]
    )
    assert runner.FSI_RUBRIC not in b_prompt["system"]
    assert c_prompt["system"].count(runner.FSI_RUBRIC) == 1


@pytest.mark.parametrize(
    "mutation", ["bytes", "block", "source_hash", "future", "quarter", "missing_blocks"]
)
def test_source_fail_closed_before_provider_or_run_creation(tmp_path, package, mutation):
    prepared, contents = copy.deepcopy(package)
    if mutation == "bytes":
        contents[next(iter(contents))] = b"different"
    elif mutation == "block":
        prepared["sources"]["blocks"][0]["text"] += " Unbacked statement."
    elif mutation == "source_hash":
        prepared["sources"]["blocks"][0]["source_hash"] = runner.compute_sha256("demand_momentum")
    elif mutation == "future":
        prepared["sources"]["documents"][0]["available_at"] = "2023-01-01T00:00:00+00:00"
    elif mutation == "quarter":
        prepared["quant_context"]["quarter"] = "FY2023-Q3"
    else:
        prepared["sources"]["blocks"] = []
    provider = SyntheticProvider()
    with pytest.raises((ValueError, KeyError)):
        run(tmp_path, (prepared, contents), provider)
    assert not provider.requests
    with sqlite3.connect(tmp_path / "candidate.db") as conn:
        assert conn.execute("SELECT count(*) FROM s2_experiment_runs").fetchone()[0] == 0


@pytest.mark.parametrize(
    "failure", ["exception", "bad_schema", "bad_status", "no_features", "missing_challenge"]
)
def test_failed_or_incomplete_run_never_claims_completed(tmp_path, package, failure):
    def transform(stage, raw):
        if stage == "extract" and failure == "exception":
            raise RuntimeError("Potentially sensitive provider detail")
        if stage == "extract" and failure == "bad_schema":
            raw["structured_output"] = {"bad": "shape"}
        if stage == "extract" and failure == "bad_status":
            raw["execution_metadata"]["provider_execution_status"] = "quota_limited"
        if stage == "synthesize" and failure == "no_features":
            raw["structured_output"]["features"] = []
        if stage == "challenge" and failure == "missing_challenge":
            raw["structured_output"]["challenges"] = []
        return raw

    provider = SyntheticProvider(transform)
    summary, database = run(tmp_path, package, provider)
    assert summary["status"] == (
        "INCOMPLETE" if failure in {"no_features", "missing_challenge"} else "FAILED"
    )
    result = verifier.verify(database, [summary["run_id"]])
    assert result["status"] == result["lineage_status"] == "UNVERIFIED"
    assert len(provider.requests) == summary["calls_made"]
    assert summary["calls_made"] <= 3
    assert b"Potentially sensitive" not in database.read_bytes()
    if failure == "exception":
        with sqlite3.connect(database) as conn:
            assert conn.execute(
                "SELECT raw_response,response_hash,error_type FROM s2_provider_calls"
            ).fetchone() == (None, None, "RuntimeError")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE s2_provider_calls SET request_hash='false'",
        "UPDATE s2_provider_calls SET raw_response='{}'",
        "UPDATE s2_evidence SET source_hash='false'",
        "UPDATE s2_evidence SET call_id=999",
        "UPDATE s2_evidence SET run_id=999",
        "UPDATE s2_features SET supporting_keys='[]'",
        "UPDATE s2_features SET confidence=0.99",
        "UPDATE s2_challenges SET evidence_keys='[]'",
        "UPDATE s2_source_documents SET content=X'00'",
        "UPDATE s2_experiment_runs SET calls_made=0",
    ],
)
def test_tampered_lineage_is_inconsistent(tmp_path, package, sql):
    summary, database = run(tmp_path, package)
    assert summary["status"] == "COMPLETED", summary
    with sqlite3.connect(database) as conn:
        conn.execute(sql)
    assert verifier.verify(database, [summary["run_id"]])["lineage_status"] == "INCONSISTENT"


def test_dry_run_missing_inputs_is_not_readiness_or_schema_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert runner.main([]) == 0
    assert list(tmp_path.iterdir()) == []
    assert (
        runner.run_dry_run("FY2023-Q2")["preflight"]["preflight_status"]
        == "UNVERIFIED_MISSING_INPUTS"
    )
    with pytest.raises(SystemExit):
        runner.main(["--live"])
    assert list(tmp_path.iterdir()) == []


def test_existing_database_never_auto_migrates(tmp_path):
    database = tmp_path / "legacy.db"
    database.write_bytes(b"legacy bytes")
    with pytest.raises(FileExistsError):
        runner.init_candidate_database(database)
    assert database.read_bytes() == b"legacy bytes"


def test_missing_provenance_never_gets_confidence_fallback():
    with pytest.raises(ValueError):
        runner.compute_item_confidence([{"topic": "demand_momentum", "key": "e"}])


def test_all_opt_ins_cannot_unlock_unverified_live_runtime(tmp_path, package, capsys):
    with pytest.raises(SystemExit):
        runner.main(
            [
                "--live",
                "--authorize-live",
                "--model",
                "fixture",
                "--prepared-context",
                str(tmp_path / "must-not-read.json"),
                "--source-dir",
                str(tmp_path / "must-not-read"),
                "--output-dir",
                str(tmp_path / "must-not-create"),
            ]
        )
    assert "no-residual-provider" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
    prepared, contents = package
    provider = SyntheticProvider()
    with pytest.raises(ValueError, match="Live execution is blocked"):
        runner.run_single_method(
            "method_b",
            runner.build_method_payloads("FY2023-Q2")["method_b"],
            provider,
            prepared,
            tmp_path / "must-not-open.db",
            source_contents=contents,
            execution_mode="LIVE_EXECUTION",
        )
    assert not provider.requests
    assert list(tmp_path.iterdir()) == []
