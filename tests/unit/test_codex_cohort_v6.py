"""Cohort dispatch cannot bypass a failed receipt, input, or predecessor gate."""

import importlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("run_codex_validation_v6")


def plan_for(runner):
    ref = {"path": "/synthetic/pilot.json", "sha256": "a" * 64, "error_type": None}
    plan = {
        "version": runner.PLAN_VERSION, "contract": runner.contract(),
        "quarters": list(runner.QUARTERS[1:]), "pilot_receipt": ref,
        "inputs": {quarter: {"quarter": quarter} for quarter in runner.QUARTERS[1:]},
    }
    return plan, ref


@pytest.mark.parametrize("drift", ["version", "prompt", "order", "duplicate", "pilot", "quarter_identity"])
def test_cohort_plan_rejects_contract_order_and_pilot_drift(runner, drift):
    plan, ref = plan_for(runner)
    runner.validate_plan(plan, ref)
    changed = deepcopy(plan)
    if drift == "version":
        changed["version"] = "CodexCohortPlanV5"
    elif drift == "prompt":
        changed["contract"]["prompt_version"] = "PromptSetV5"
    elif drift == "order":
        changed["quarters"].reverse()
    elif drift == "duplicate":
        changed["quarters"][-1] = changed["quarters"][0]
    elif drift == "pilot":
        changed["pilot_receipt"]["sha256"] = "b" * 64
    else:
        changed["inputs"][runner.QUARTERS[1]]["quarter"] = runner.QUARTERS[2]
    with pytest.raises(ValueError):
        runner.validate_plan(changed, ref)


@pytest.mark.parametrize("failure", ["FAIL", "UNKNOWN", "BLOCKED", None])
def test_cohort_stops_before_later_quarter_after_non_pass(runner, failure):
    plan, _ = plan_for(runner)
    called, recorded = [], []

    def execute(quarter):
        called.append(quarter)
        return {"quarter": quarter, "gate": "PASS" if len(called) == 1 else failure}

    result = runner.execute_quarters(plan, execute, lambda rows: recorded.append(deepcopy(rows)))
    assert called == plan["quarters"][:2]
    assert result[-1]["gate"] == failure
    assert [len(rows) for rows in recorded] == [1, 2]


def test_cohort_does_not_continue_after_exception(runner):
    plan, _ = plan_for(runner)
    called = []

    def execute(quarter):
        called.append(quarter)
        raise RuntimeError("synthetic execution failure")

    with pytest.raises(RuntimeError):
        runner.execute_quarters(plan, execute, lambda _: None)
    assert called == plan["quarters"][:1]


def test_cohort_all_six_are_ordered_without_replaying_q2(runner):
    plan, _ = plan_for(runner)
    result = runner.execute_quarters(plan, lambda q: {"quarter": q, "gate": "PASS"}, lambda _: None)
    assert [row["quarter"] for row in result] == list(runner.QUARTERS[1:])


def test_execution_requires_explicit_plan_bytes_hash(runner):
    with pytest.raises(SystemExit) as exc:
        runner.main(["--plan", "missing.json", "--pilot-receipt", "p.json",
                     "--isolation-receipt", "i.json", "--kernel-receipt", "k.json"])
    assert exc.value.code == 2


@pytest.fixture
def prepared(runner, monkeypatch, tmp_path):
    context = {"synthetic": "approved context"}
    expected = {"context_hash": runner.digest(context)}
    monkeypatch.setattr(runner, "resolve_run", lambda *_: "quant")
    monkeypatch.setattr(runner, "prepare", lambda *_: context)
    monkeypatch.setattr(runner, "context_identity", lambda _: expected)
    monkeypatch.setattr(runner.gates, "verify_saved_isolation", lambda *_: {"status": "PASS"})
    monkeypatch.setattr(runner.gates, "verify_live_isolation", lambda *_: {"status": "PASS"})
    monkeypatch.setattr(runner.gates, "receipt_references_unchanged", lambda *_: {"status": "PASS"})
    monkeypatch.setattr(runner.gates, "current_user_config_hash", lambda: "config")
    launches = []

    def provider(*_, **__):
        launches.append(True)
        return SimpleNamespace(settings={}, check=lambda: {"synthetic": True})

    monkeypatch.setattr(runner, "CodexCLIProvider", provider)
    journal = SimpleNamespace(path=tmp_path, process_state_unknown=False, emit=lambda *_, **__: None)
    refs = {name: {"path": name, "sha256": name} for name in ["isolation", "kernel", "plan", "pilot"]}
    gate = {"discovery_receipt": {}, "configuration_hash_before": "config"}
    return SimpleNamespace(context=context, expected=expected, journal=journal, refs=refs, gate=gate,
                           launches=launches, settings=SimpleNamespace(qve_raw_dir=tmp_path))


@pytest.mark.parametrize("failure", ["context", "kernel", "receipts", "live"])
def test_preflight_failure_does_not_reach_analysis(runner, monkeypatch, prepared, failure):
    expected = prepared.expected
    if failure == "context":
        expected = {"context_hash": "changed"}
    elif failure == "kernel":
        monkeypatch.setattr(runner.gates, "verify_saved_isolation", lambda *_: {"status": "FAIL"})
    elif failure == "receipts":
        monkeypatch.setattr(runner.gates, "receipt_references_unchanged", lambda *_: {"status": "FAIL"})
    else:
        monkeypatch.setattr(runner.gates, "verify_live_isolation", lambda *_: {"status": "FAIL"})
    monkeypatch.setattr(runner.gates, "analyze_approved_context", lambda *_: pytest.fail("historical model started"))
    row = runner.run_quarter(None, prepared.settings, "FY2023-Q3", expected, prepared.refs,
                             prepared.gate, {}, prepared.journal)
    assert row["gate"] == "FAIL" and row["model_started"] is False
    assert prepared.launches == ([True] if failure == "live" else [])


@pytest.mark.parametrize("fresh,preserved,unknown", [(True, True, False), (False, True, False), (True, False, False), (True, True, True)])
def test_actual_dispatch_binds_context_and_checks_new_run_and_preservation(
    runner, monkeypatch, prepared, fresh, preserved, unknown
):
    snapshot = SimpleNamespace(id=4, analysis_run_id=16 if fresh else 15, metadata_json={"missing_features": []})
    captured = []

    def analyze(*args, **kwargs):
        captured.append((args, kwargs))
        prepared.journal.process_state_unknown = unknown
        return snapshot

    monkeypatch.setattr(runner.gates, "analyze", analyze)
    hashes = iter([{"rows": 1}, {"rows": 1 if preserved else 2}])
    monkeypatch.setattr(runner.gates, "preservation_hashes", lambda _: next(hashes))
    monkeypatch.setattr(runner, "run_rows", lambda *_: {"calls": [], "rejected": []})
    monkeypatch.setattr(runner, "assess_run", lambda *_: {"gate": "PASS", "blockers": []})
    db = SimpleNamespace(scalar=lambda _: 15, commit=lambda: None)
    row = runner.run_quarter(db, prepared.settings, "FY2023-Q3", prepared.expected,
                             prepared.refs, prepared.gate, {}, prepared.journal)
    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args[0] is db
    assert kwargs["refresh"] is True
    assert kwargs["prepared_context"] is prepared.context
    assert kwargs["approved_context_hash"] == runner.digest(prepared.context)
    assert row["gate"] == ("PASS" if fresh and preserved and not unknown else "FAIL")


def test_unknown_process_state_blocks_even_discovery(runner, prepared):
    prepared.journal.process_state_unknown = True
    row = runner.run_quarter(None, prepared.settings, "FY2023-Q3", prepared.expected,
                             prepared.refs, prepared.gate, {}, prepared.journal)
    assert row["blockers"] == ["termination_unconfirmed"]
    assert row["model_started"] is False
    assert prepared.launches == []


@pytest.mark.parametrize("fault", ["version", "snapshot", "assessment", "preflight", "terminal"])
def test_pilot_receipt_must_match_database_and_terminal_evidence(runner, monkeypatch, tmp_path, fault):
    plan, _ = plan_for(runner)
    isolation = {"path": "isolation", "sha256": "i"}
    kernel = {"path": "kernel", "sha256": "k"}
    pilot = {**plan["contract"], "quarter_package_version": plan["contract"]["package_version"],
             "quarter": "FY2023-Q2", "gate": "PASS", "blockers": [],
             "isolation_receipt": isolation, "kernel_receipt": kernel,
             "analysis_run_id": 15, "snapshot_id": 4, "context_hash": "context",
             "preflight_receipt": "preflight", "preflight_sha256": "preflight_hash",
             "attempt_dir": str(tmp_path)}
    (tmp_path / "progress.jsonl").write_text('{"event":"finished","status":"completed"}\n')
    rows = {"run": SimpleNamespace(context_json={}), "snapshot": SimpleNamespace(id=4)}
    monkeypatch.setattr(runner, "run_rows", lambda *_: rows)
    monkeypatch.setattr(runner.gates, "verify_q2_inputs", lambda *_, **__: {"status": "PASS"})
    monkeypatch.setattr(runner, "assess_run", lambda *_: {"gate": "PASS", "blockers": []})
    monkeypatch.setattr(runner, "reference", lambda _: ({"sha256": "preflight_hash"}, {"status": "PASS", "approved_context_sha256": "context"}))
    runner.verify_pilot(None, pilot, isolation, kernel)
    if fault == "version":
        pilot["prompt_version"] = "PromptSetV5"
    elif fault == "snapshot":
        pilot["snapshot_id"] = 3
    elif fault == "assessment":
        monkeypatch.setattr(runner, "assess_run", lambda *_: {"gate": "FAIL", "blockers": ["unsafe"]})
    elif fault == "preflight":
        pilot["preflight_sha256"] = "changed"
    else:
        (tmp_path / "progress.jsonl").write_text('{"event":"finished","status":"unknown"}\n')
    with pytest.raises(ValueError):
        runner.verify_pilot(None, pilot, isolation, kernel)


def test_prepare_plan_closes_session_cleanly_and_does_not_start_cli(runner, monkeypatch, tmp_path):
    import sqlite3

    from sqlalchemy import text

    dbpath = tmp_path / "formal.db"
    with sqlite3.connect(dbpath) as db:
        db.execute("CREATE TABLE marker (value TEXT)")
        db.execute("INSERT INTO marker VALUES ('preserve')")
    before = dbpath.read_bytes()
    monkeypatch.setattr(runner, "Settings", lambda: SimpleNamespace(qve_database_url="sqlite:///" + str(dbpath)))
    monkeypatch.setattr(runner, "reference", lambda path: ({"path": str(path), "sha256": "a" * 64}, {}))
    monkeypatch.setattr(runner, "verify_pilot", lambda *_: None)
    monkeypatch.setattr(runner.gates, "verify_saved_isolation", lambda *_: {"status": "PASS"})
    monkeypatch.setattr(runner, "CodexCLIProvider", lambda *_: pytest.fail("CLI started during preparation"))

    def prepare(db, *_):
        assert db.scalar(text("SELECT value FROM marker")) == "preserve"
        return {"quarters": list(runner.QUARTERS[1:])}

    monkeypatch.setattr(runner, "prepare_plan", prepare)
    assert runner.main(["--prepare-plan", str(tmp_path / "plan.json"), "--pilot-receipt", "p.json",
                        "--isolation-receipt", "i.json", "--kernel-receipt", "k.json"]) == 0
    assert dbpath.read_bytes() == before


@pytest.mark.parametrize("observed_timeout", [600, 180])
def test_resumed_dispatch_uses_and_attests_new_budget(runner, monkeypatch, prepared, observed_timeout):
    captured = {}

    def provider(model, timeout):
        captured["timeout"] = timeout
        captured["provider"] = SimpleNamespace(
            settings={"timeout_seconds": timeout, "max_attempts": 2}, check=lambda: {}
        )
        return captured["provider"]

    def analyze(*args, **kwargs):
        captured["context"] = kwargs["prepared_context"]
        return SimpleNamespace(id=6, analysis_run_id=20, metadata_json={"missing_features": []})

    def rows(*_):
        settings = captured["provider"].settings
        return {"run": SimpleNamespace(settings_json=settings), "rejected": [], "calls": [
            SimpleNamespace(status="valid", stage="extract", raw_output={"execution_metadata": {
                **settings, "stage_timeout_seconds": observed_timeout, "retry_count": 0,
            }})
        ]}

    monkeypatch.setattr(runner, "CodexCLIProvider", provider)
    monkeypatch.setattr(runner.gates, "analyze", analyze)
    monkeypatch.setattr(runner.gates, "preservation_hashes", lambda _: {"preserved": True})
    monkeypatch.setattr(runner, "run_rows", rows)
    monkeypatch.setattr(runner, "assess_run", lambda *_: {"gate": "PASS", "blockers": []})
    db = SimpleNamespace(scalar=lambda _: 19, commit=lambda: None)
    row = runner.run_quarter(db, prepared.settings, "FY2024-Q2", prepared.expected, prepared.refs,
                             prepared.gate, {}, prepared.journal, budget_version="CodexStageBudgetV2")
    assert captured["timeout"] == 600
    assert captured["context"] is prepared.context
    assert row["execution_budget"]["version"] == "CodexStageBudgetV2"
    assert row["gate"] == ("PASS" if observed_timeout == 600 else "FAIL")


def test_unknown_budget_cannot_start_provider(runner, prepared):
    with pytest.raises(ValueError, match="Unknown execution budget"):
        runner.run_quarter(None, prepared.settings, "FY2024-Q2", prepared.expected, prepared.refs,
                           prepared.gate, {}, prepared.journal, budget_version="unbounded")
    assert prepared.launches == []
