"""Explicit accepted snapshots and comparable live reruns, never AI human verdicts."""

import importlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def repeat(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    return importlib.import_module("run_codex_repeatability_v6")


def sample_rows():
    settings = {"timeout_seconds": 180, "max_attempts": 2}
    calls = [
        SimpleNamespace(
            stage=stage,
            request_hash=stage,
            raw_output={
                "execution_metadata": {
                    **settings,
                    "stage_timeout_seconds": seconds,
                    "retry_count": 0,
                }
            },
        )
        for stage, seconds in (("extract", 180), ("synthesize", 600), ("challenge", 600))
    ]
    for index, call in enumerate(calls):
        call.id = index + 1
    return {"run": SimpleNamespace(settings_json=settings), "calls": calls}


def test_legacy_effective_limits_are_read_from_actual_calls(repeat):
    rows = sample_rows()
    assert repeat.effective_budget(rows) == repeat.base.execution_budget("CodexStageBudgetV1")
    assert "execution_budget" not in rows["run"].settings_json


@pytest.mark.parametrize(
    "fault",
    ["run_timeout", "call_timeout", "stage", "attempts", "retry", "cache", "declared_budget"],
)
def test_actual_budget_or_reused_calls_cannot_claim_same_conditions(repeat, fault):
    rows = sample_rows()
    meta = rows["calls"][0].raw_output["execution_metadata"]
    if fault == "run_timeout":
        rows["run"].settings_json["timeout_seconds"] = 600
    elif fault == "call_timeout":
        meta["stage_timeout_seconds"] = 600
    elif fault == "stage":
        rows["calls"][0].stage = "unknown"
    elif fault == "attempts":
        meta["max_attempts"] = 3
    elif fault == "retry":
        meta["retry_count"] = 2
    elif fault == "cache":
        meta["reused_from_call_id"] = 123
    else:
        rows["run"].settings_json["execution_budget"] = repeat.base.execution_budget(
            "CodexStageBudgetV2"
        )
    with pytest.raises(ValueError):
        repeat.effective_budget(rows)


def test_cards_use_explicit_v6_snapshots_and_never_select_oldest_or_fill_verdict(repeat):
    accepted = [
        {
            "quarter": q,
            "analysis_run_id": n,
            "snapshot_id": n + 100,
            "receipt": {"path": f"/receipts/{q}", "sha256": "a" * 64},
        }
        for q, n in zip(repeat.base.QUARTERS, (15, 17, 18, 20, 21, 22, 23), strict=True)
    ]
    dossiers = {q: {"path": f"/dossiers/{q}", "sha256": "b" * 64} for q in repeat.base.QUARTERS[:5]}
    cards = repeat.review_cards({"accepted_results": accepted}, dossiers)
    assert len(cards) == 35
    assert {c["analysis_run_id"] for c in cards} == {15, 17, 18, 20, 21}
    assert len({(c["quarter"], c["category"]) for c in cards}) == 35
    for c in cards:
        assert c["dossier"] == dossiers[c["quarter"]]
        assert all(
            c[k] is None
            for k in ("verdict", "reviewer", "reviewed_at", "notes", "semantic_support")
        )
        assert c["evidence_ids"] == [] and c["status"] == "pending_human_review"


@pytest.mark.parametrize("fault", ["missing", "duplicate", "reordered", "no_snapshot"])
def test_cards_reject_incomplete_or_ambiguous_accepted_set(repeat, fault):
    accepted = [
        {"quarter": q, "analysis_run_id": i + 1, "snapshot_id": i + 1, "receipt": {}}
        for i, q in enumerate(repeat.base.QUARTERS)
    ]
    if fault == "missing":
        accepted.pop()
    elif fault == "duplicate":
        accepted[1] = deepcopy(accepted[0])
    elif fault == "reordered":
        accepted[0], accepted[1] = accepted[1], accepted[0]
    else:
        accepted[0]["snapshot_id"] = None
    with pytest.raises(ValueError):
        repeat.review_cards({"accepted_results": accepted}, {})


@pytest.fixture
def pair(repeat, monkeypatch):
    a, b = sample_rows(), sample_rows()
    budget = repeat.base.execution_budget(repeat.BUDGET_VERSION)
    b["run"].settings_json["execution_budget"] = budget
    for c in b["calls"]:
        c.raw_output["execution_metadata"]["execution_budget"] = budget
    for rows, value in ((a, -1), (b, 1)):
        rows["run"].policy_version = "AIAnalystPolicyV3"
        rows["snapshot"] = SimpleNamespace(
            metadata_json={"missing_features": ["guidance_visibility"]}
        )
        rows["features"] = [SimpleNamespace(feature_name="demand_momentum", feature_value=value)]
    metrics = {
        k: True
        for k in (
            "same_provider",
            "same_context",
            "same_prompt_version",
            "same_schema_version",
            "same_package_hash",
            "same_requested_model",
            "same_cli_version",
        )
    }
    metrics.update(
        same_exact_prompt_hashes=False,
        semantic_stability="human_interpretation_required",
        opposite_sign_features=["demand_momentum"],
    )
    monkeypatch.setattr(repeat.base, "run_rows", lambda _, run_id: a if run_id == 15 else b)
    monkeypatch.setattr(repeat, "compare", lambda *_: deepcopy(metrics))
    return a, b, metrics


def test_generated_later_prompt_differences_are_not_configuration_drift(repeat, pair):
    _, b, _ = pair
    b["calls"][1].request_hash = "new-evidence-dependent-synthesis"
    result = repeat.compare_pair(None, 15, 24)
    assert result["gate"] == "PASS" and result["comparison_complete"]
    assert result["same_exact_prompt_hashes"] is False
    assert result["semantic_stability"] == "human_interpretation_required"
    assert result["opposite_sign_features"] == ["demand_momentum"]
    assert result["actual_model_identity_verified"] is False
    assert result["m4_1_final_pass"] is False
    diff = next(f for f in result["feature_differences"] if f["feature"] == "demand_momentum")
    assert diff["delta"] == 2 and diff["opposite_sign"] is True


@pytest.mark.parametrize(
    "fault", ["extraction", "policy", "model", "context", "budget_attestation"]
)
def test_repeat_configuration_drift_fails_comparison(repeat, pair, fault):
    _, b, metrics = pair
    if fault == "extraction":
        b["calls"][0].request_hash = "different-source"
    elif fault == "policy":
        b["run"].policy_version = "different"
    elif fault == "model":
        metrics["same_requested_model"] = False
    elif fault == "context":
        metrics["same_context"] = False
    else:
        b["calls"][0].raw_output["execution_metadata"].pop("execution_budget")
    result = repeat.compare_pair(None, 15, 24)
    assert result["gate"] == "FAIL" and not result["comparison_complete"]


def test_reusing_baseline_cannot_count_as_a_repeat(repeat, pair):
    with pytest.raises(ValueError):
        repeat.compare_pair(None, 15, 15)


def test_failed_repeat_does_not_compare_or_start_q3(repeat, monkeypatch, tmp_path):
    dispatched = []
    plan = {
        "quarters": list(repeat.base.QUARTERS[:2]),
        "accepted_results": [
            {"quarter": q, "analysis_run_id": i}
            for q, i in zip(repeat.base.QUARTERS[:2], [15, 17], strict=True)
        ],
        "accepted_data_hashes": {q: "hash" for q in repeat.base.QUARTERS[:2]},
        "inputs": {q: {} for q in repeat.base.QUARTERS[:2]},
    }
    monkeypatch.setattr(repeat.base, "run_rows", lambda *_: {})
    monkeypatch.setattr(repeat, "rows_hash", lambda *_: "hash")

    def fail_run(*args, **kwargs):
        dispatched.append(args[2])
        return {"gate": "FAIL", "analysis_run_id": 24, "blockers": ["timeout"]}

    monkeypatch.setattr(repeat.base, "run_quarter", fail_run)
    monkeypatch.setattr(
        repeat, "compare_pair", lambda *_: pytest.fail("Failed run cannot be compared")
    )
    journal = SimpleNamespace(path=tmp_path)
    results = repeat.base.execute_quarters(
        plan,
        lambda q: repeat.execute_repeat(None, None, q, plan, {}, {}, {}, journal),
        lambda _: None,
    )
    assert dispatched == ["FY2023-Q2"] and results[0]["comparison"] is None


@pytest.mark.parametrize(
    "fault", [None, "gate", "unknown", "count", "order", "inherited", "refs", "terminal", "attempt"]
)
def test_completed_cohort_requires_terminal_evidence_and_exact_results(repeat, tmp_path, fault):
    origin = tmp_path / "attempt"
    origin.mkdir()
    plan = {
        "references": {"pilot": {}},
        "inherited_results": [{"quarter": "a"}],
        "execution_budget": {},
        "quarters": ["q1", "q2"],
    }
    final = {
        "gate": "PASS",
        "required_quarters": 7,
        "completed_quarters": 7,
        "process_state_unknown": False,
        "inherited_results": deepcopy(plan["inherited_results"]),
        "execution_budget": {},
        "references": {"pilot": {}, "plan": {}},
        "results": [{"quarter": q, "gate": "PASS"} for q in plan["quarters"]],
        "attempt_id": "attempt",
    }
    terminal = {"event": "finished", "status": "completed", "attempt_id": "attempt"}
    if fault == "gate":
        final["gate"] = "FAIL"
    elif fault == "unknown":
        final["process_state_unknown"] = True
    elif fault == "count":
        final["completed_quarters"] = 6
    elif fault == "order":
        final["results"].reverse()
    elif fault == "inherited":
        final["inherited_results"] = []
    elif fault == "refs":
        final["references"]["pilot"] = {"sha256": "changed"}
    elif fault == "terminal":
        terminal["status"] = "unknown"
    elif fault == "attempt":
        terminal["attempt_id"] = "other"
    (origin / "progress.jsonl").write_text(__import__("json").dumps(terminal) + "\n")
    if fault:
        with pytest.raises(ValueError):
            repeat.validate_completed_receipt(final, plan, origin)
    else:
        repeat.validate_completed_receipt(final, plan, origin)


def test_bad_plan_hash_is_rejected_before_attempt_or_provider_start(repeat, tmp_path, monkeypatch):
    import json
    import sqlite3

    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    monkeypatch.setattr(
        repeat, "Settings", lambda: SimpleNamespace(qve_database_url="sqlite:///" + str(path))
    )
    monkeypatch.setattr(repeat, "prepare_plan", lambda *_: {})
    monkeypatch.setattr(
        repeat, "AttemptJournal", lambda *_, **__: pytest.fail("No attempt before hash gate")
    )
    for name in ["cohort.json", "plan.json"]:
        (tmp_path / name).write_text(json.dumps({}))
    with pytest.raises(ValueError):
        repeat.main(
            [
                "--cohort-receipt",
                str(tmp_path / "cohort.json"),
                "--plan",
                str(tmp_path / "plan.json"),
                "--plan-sha256",
                "a" * 64,
            ]
        )


def test_review_export_is_explicit_immutable_and_no_human_submission(repeat, tmp_path, monkeypatch):
    import hashlib
    import json

    accepted = [
        {"quarter": q, "analysis_run_id": n, "snapshot_id": n + 100, "receipt": {}}
        for q, n in zip(repeat.base.QUARTERS, (15, 17, 18, 20, 21, 22, 23), strict=True)
    ]
    selected_ids = []

    def load_rows(_, run_id):
        selected_ids.append(run_id)
        return {
            "run": SimpleNamespace(
                context_json={
                    "quant_context": {"information_cutoff": "2022-08-25T13:30:00Z"},
                    "sources": {"documents": []},
                }
            ),
            "snapshot": SimpleNamespace(
                id=run_id + 100,
                metadata_json={"missing_features": ["guidance_visibility"], "sections": {}},
            ),
            "features": [],
            "evidence": [],
            "challenges": [],
            "rejected": [],
        }

    monkeypatch.setattr(repeat.base, "run_rows", load_rows)
    monkeypatch.setattr(repeat, "rows_hash", lambda _: "hash")
    monkeypatch.setattr(
        repeat, "serialized", lambda row: {"id": row.id, "metadata_json": row.metadata_json}
    )
    plan = {
        "accepted_results": accepted,
        "accepted_data_hashes": {q: "hash" for q in repeat.base.QUARTERS},
    }
    out = tmp_path / "review"
    assert repeat.export_review(None, plan, out)["generated_cards"] == 35
    assert selected_ids == [15, 17, 18, 20, 21]
    assert len(list((out / "cards").glob("*.md"))) == 35
    assert json.loads((out / "human-review-status.json").read_text())["correct_rate"] is None
    manifest = json.loads((out / "manifest.json").read_text())
    assert all(
        hashlib.sha256(Path(r["path"]).read_bytes()).hexdigest() == r["sha256"]
        for r in manifest["files"]
    )
    before = (out / "human-review-cards.generated.json").read_bytes()
    with pytest.raises(FileExistsError):
        repeat.export_review(None, plan, out)
    assert (out / "human-review-cards.generated.json").read_bytes() == before


def test_accepted_result_must_bind_the_actual_expected_context(repeat, tmp_path, monkeypatch):
    import json

    context = {"value": "approved"}
    expected = {"context_hash": repeat.base.digest(context)}
    budget = repeat.base.execution_budget("CodexStageBudgetV2")
    preflight = {
        "status": "PASS",
        "references": {},
        "execution_budget": budget,
        "approved_context_sha256": "forged-other-context",
    }
    (tmp_path / "context.json").write_text(json.dumps(context))
    (tmp_path / "preflight.json").write_text(json.dumps(preflight))
    row = {
        "quarter": "FY2024-Q2",
        "references": {},
        "model_started": True,
        "preservation_unchanged": True,
        "execution_budget": budget,
        "context_hash": "forged-other-context",
        "preflight_sha256": repeat.base.reference(tmp_path / "preflight.json")[0]["sha256"],
    }
    (tmp_path / "result.json").write_text(json.dumps(row))
    monkeypatch.setattr(repeat.base, "context_identity", lambda _: expected)
    monkeypatch.setattr(
        repeat.base, "run_rows", lambda *_: pytest.fail("Reject mixed context before DB selection")
    )
    with pytest.raises(ValueError):
        repeat.verify_new_cohort_row(None, row, expected, {}, tmp_path, budget)
