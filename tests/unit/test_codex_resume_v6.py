"""A resumed cohort must revalidate its passed prefix and pin execution limits."""
import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture
def base(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("run_codex_validation_v6")


def test_explicit_budget_is_bounded_and_does_not_change_the_legacy_default(base):
    old = base.execution_budget("CodexStageBudgetV1")
    new = base.execution_budget("CodexStageBudgetV2")
    assert old["stage_seconds"] == {"extract": 180, "synthesize": 600, "challenge": 600}
    assert new["stage_seconds"] == {"extract": 600, "synthesize": 600, "challenge": 600}
    assert old["max_attempts"] == new["max_attempts"] == 2
    assert old["chunk_characters"] == new["chunk_characters"] == 18000
    with pytest.raises(ValueError):
        base.execution_budget("unbounded")


@pytest.mark.parametrize("fault", ["metadata", "actual_timeout", "retry", "stage", "run"])
def test_budget_attestation_checks_actual_calls_and_run_settings(base, fault):
    from types import SimpleNamespace

    budget = base.execution_budget("CodexStageBudgetV2")
    settings = {"execution_budget": budget, "timeout_seconds": 600, "max_attempts": 2}
    meta = {**settings, "stage_timeout_seconds": 600, "retry_count": 0}
    call = SimpleNamespace(stage="extract", raw_output={"execution_metadata": meta})
    rows = {"run": SimpleNamespace(settings_json=deepcopy(settings)), "calls": [call]}
    assert base.verify_execution_budget(rows, budget) == []
    if fault == "metadata":
        meta.pop("execution_budget")
    elif fault == "actual_timeout":
        meta["stage_timeout_seconds"] = 180
    elif fault == "retry":
        meta["retry_count"] = 2
    elif fault == "stage":
        call.stage = "unknown"
    else:
        rows["run"].settings_json["timeout_seconds"] = 0
    assert base.verify_execution_budget(rows, budget) == ["execution_budget_mismatch"]


@pytest.fixture
def checkpoint_fixture(base, monkeypatch, tmp_path):
    from types import SimpleNamespace

    resume = importlib.import_module("resume_codex_validation_v6")
    origin = tmp_path / "synthetic-attempt"
    origin.mkdir()

    def put(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return base.reference(path)[0]

    refs = {name: put(tmp_path / (name + ".json"), {}) for name in ("pilot", "isolation", "kernel")}
    original = {"version": base.PLAN_VERSION, "contract": base.contract(),
                "quarters": list(base.QUARTERS[1:]), "pilot_receipt": refs["pilot"],
                "inputs": {q: {"quarter": q} for q in base.QUARTERS[1:]}}
    original_ref = put(tmp_path / "original-plan.json", original)
    previous_refs = {**refs, "plan": original_ref}
    rows = []
    database = {}
    for i, quarter in enumerate(base.QUARTERS[1:4]):
        directory = origin / "quarters" / quarter
        context = {"quarter": quarter}
        put(directory / "context.json", context)
        preflight_ref = put(directory / "preflight.json", {
            "status": "PASS", "approved_context_sha256": base.digest(context), "references": previous_refs,
        })
        row = {"quarter": quarter, "gate": "PASS" if i < 2 else "FAIL", "blockers": [],
               "references": previous_refs, "analysis_run_id": i + 17, "snapshot_id": i + 5,
               "model_started": True, "preservation_unchanged": True,
               "context_hash": base.digest(context), "preflight_sha256": preflight_ref["sha256"],
               "calls": 1, "valid_calls": 1, "missing_features": []}
        put(directory / "result.json", row)
        rows.append(row)
        database[i + 17] = {
            "run": SimpleNamespace(),
            "snapshot": SimpleNamespace(id=i + 5, metadata_json={"missing_features": []}),
            "calls": [SimpleNamespace(status="valid", stage="extract", raw_output={"execution_metadata": {
                "stage_timeout_seconds": 180, "timeout_seconds": 180, "max_attempts": 2,
            }})],
        }
    previous = {"gate": "FAIL", "process_state_unknown": False, "required_quarters": 7,
                "completed_quarters": 3, "attempt_id": origin.name,
                "references": previous_refs, "results": rows}
    previous_ref = put(origin / "validation.json", previous)
    (origin / "progress.jsonl").write_text(json.dumps({"event": "finished", "status": "failed", "attempt_id": origin.name}) + "\n")
    monkeypatch.setattr(base, "verify_pilot", lambda *_: None)
    monkeypatch.setattr(base.gates, "verify_saved_isolation", lambda *_: {"status": "PASS"})
    monkeypatch.setattr(base, "prepare_plan", lambda *_: deepcopy(original))
    monkeypatch.setattr(base, "context_identity", lambda context: context)
    monkeypatch.setattr(base, "run_rows", lambda _, run_id: database[run_id])
    monkeypatch.setattr(base, "assess_run", lambda *_: {"gate": "PASS", "blockers": []})
    monkeypatch.setattr(base, "CodexCLIProvider", lambda *_: pytest.fail("No CLI during read-only preparation"))
    return SimpleNamespace(resume=resume, origin=origin, previous=previous, previous_ref=previous_ref,
                           refs=refs, original=original, original_ref=original_ref, put=put, database=database)


def test_resume_revalidates_prefix_then_selects_exact_remaining_quarters(checkpoint_fixture, base):
    f = checkpoint_fixture
    plan = f.resume.prepare_resume_plan(None, None, f.previous_ref, f.refs)
    assert plan["quarters"] == list(base.QUARTERS[3:])
    assert [r["quarter"] for r in plan["inherited_results"]] == list(base.QUARTERS[1:3])
    assert plan["execution_budget"]["version"] == "CodexStageBudgetV2"
    assert all(r["execution_budget"]["version"] == "CodexStageBudgetV1" for r in plan["inherited_results"])
    assert plan["inputs"] == f.original["inputs"]
    assert plan["repeatability"] == plan["human_reviews"] == "NOT_RUN"


@pytest.mark.parametrize("fault", ["order", "gap", "unknown", "terminal", "result", "reference", "plan_bytes", "count", "attempt"])
def test_corrupt_checkpoint_cannot_authorize_resume(checkpoint_fixture, fault):
    f = checkpoint_fixture
    changed = deepcopy(f.previous)
    if fault == "order":
        changed["results"][0], changed["results"][1] = changed["results"][1], changed["results"][0]
    elif fault == "gap":
        changed["results"][0]["gate"] = "FAIL"
    elif fault == "unknown":
        changed["process_state_unknown"] = True
    elif fault == "terminal":
        (f.origin / "progress.jsonl").write_text('{"event":"finished","status":"unknown"}\n')
    elif fault == "result":
        f.put(f.origin / "quarters" / "FY2023-Q3" / "result.json", {"gate": "PASS"})
    elif fault == "reference":
        changed["references"]["isolation"]["sha256"] = "a" * 64
    elif fault == "plan_bytes":
        Path(f.original_ref["path"]).write_text("{}")
    elif fault == "count":
        changed["completed_quarters"] = 7
    else:
        changed["attempt_id"] = "some-other-attempt"
    previous_ref = f.put(f.origin / "validation.json", changed)
    with pytest.raises(ValueError):
        f.resume.prepare_resume_plan(None, None, previous_ref, f.refs)


@pytest.mark.parametrize("fault", ["snapshot", "call_count", "valid_count", "assessment", "context", "preflight", "budget", "inputs"])
def test_inherited_pass_requires_database_context_and_budget_match(checkpoint_fixture, base, monkeypatch, fault):
    f = checkpoint_fixture
    rows = f.database[17]
    if fault == "snapshot":
        rows["snapshot"].id = 999
    elif fault == "call_count":
        rows["calls"].append(deepcopy(rows["calls"][0]))
    elif fault == "valid_count":
        rows["calls"][0].status = "invalid_or_unavailable"
    elif fault == "assessment":
        monkeypatch.setattr(base, "assess_run", lambda *_: {"gate": "FAIL", "blockers": ["unsafe"]})
    elif fault == "context":
        f.put(f.origin / "quarters" / "FY2023-Q3" / "context.json", {"quarter": "changed"})
    elif fault == "preflight":
        f.put(f.origin / "quarters" / "FY2023-Q3" / "preflight.json", {"status": "PASS"})
    elif fault == "budget":
        rows["calls"][0].raw_output["execution_metadata"]["stage_timeout_seconds"] = 600
    else:
        monkeypatch.setattr(base, "prepare_plan", lambda *_: {**f.original, "inputs": {}})
    with pytest.raises(ValueError):
        f.resume.prepare_resume_plan(None, None, f.previous_ref, f.refs)


@pytest.mark.parametrize("field", ["quarters", "inputs", "inherited_results", "execution_budget", "references"])
def test_frozen_resume_plan_rejects_runtime_mutation(checkpoint_fixture, field):
    f = checkpoint_fixture
    expected = f.resume.prepare_resume_plan(None, None, f.previous_ref, f.refs)
    changed = deepcopy(expected)
    changed[field] = None
    with pytest.raises(ValueError):
        f.resume.require_exact_plan(changed, expected)


def test_resume_stops_on_first_new_failure_without_replaying_inherited(checkpoint_fixture, base):
    f = checkpoint_fixture
    plan = f.resume.prepare_resume_plan(None, None, f.previous_ref, f.refs)
    dispatched = []

    def execute(quarter):
        dispatched.append(quarter)
        return {"quarter": quarter, "gate": "FAIL"}

    result = base.execute_quarters(plan, execute, lambda _: None)
    assert dispatched == ["FY2024-Q2"]
    assert result[0]["gate"] == "FAIL"


def test_explicit_budget_reaches_real_transport_monitor_with_fake_cli(base, monkeypatch, tmp_path):
    from test_codex_pit import fake
    from test_codex_recovery import valid_gate
    from test_quarter_package import prepared

    from valuation_engine.ai import codex_pit
    from valuation_engine.ai.cli_provider import CodexCLIProvider
    from valuation_engine.ai.quarter_package import build_package

    context = prepared()
    context["quarter_package_manifest"] = build_package(context)["manifest"]
    budget = base.execution_budget("CodexStageBudgetV2")
    provider = CodexCLIProvider(codex_pit.MODEL, fake(tmp_path), budget["provider_timeout_seconds"])
    provider._pit_approved = valid_gate()
    observed = []
    monitor = codex_pit.monitor

    def capture(command, payload, cwd, seconds, **kwargs):
        observed.append(seconds)
        return monitor(command, payload, cwd, seconds, **kwargs)

    monkeypatch.setattr(codex_pit, "monitor", capture)
    result = provider.request_with_package("extract", {
        "system": "Synthetic", "task": "Test", "untrusted_data": {"blocks": []},
        "response_schema": {"type": "object"},
    }, context)
    assert observed == [600]
    assert result["execution_metadata"]["stage_timeout_seconds"] == 600
    assert result["raw_response"]["process_state"] == "confirmed_stopped"
    assert result["raw_response"]["failure_kind"] is None


def test_prepare_entry_is_read_only_and_hash_gate_precedes_attempt(checkpoint_fixture, monkeypatch, tmp_path):
    import sqlite3
    from types import SimpleNamespace

    f = checkpoint_fixture
    path = tmp_path / "readonly.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE marker (value INTEGER)")
        db.execute("INSERT INTO marker VALUES (1)")
    before = path.read_bytes()
    monkeypatch.setattr(f.resume, "Settings", lambda: SimpleNamespace(qve_database_url="sqlite:///" + str(path)))
    monkeypatch.setattr(f.resume, "AttemptJournal", lambda *_, **__: pytest.fail("No attempt before hash gate"))
    args = [part for name, ref in f.refs.items() for part in ("--" + name + "-receipt", ref["path"])]
    args += ["--previous-validation", f.previous_ref["path"]]
    plan = tmp_path / "prepared-plan.json"
    assert f.resume.main([*args, "--prepare-plan", str(plan)]) == 0
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="bytes hash mismatch"):
        f.resume.main([*args, "--plan", str(plan), "--plan-sha256", "f" * 64])
    assert path.read_bytes() == before
