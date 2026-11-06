"""Synthetic admission/bookkeeping tests; never starts AGY or another provider."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from valuation_engine.ai.agy_explanation import (
    DENIAL_PROTOCOL_ARGS_SHA256,
    DENIAL_PROTOCOL_ERROR_SHA256,
    DENIAL_PROTOCOL_MESSAGE,
    DENIAL_PROTOCOL_REPAIR_CONVERSATION,
    PINNED_REQUEST_SHA256,
    PINNED_RESEARCH_BINDING,
    PLAN_MODE_DENIALS,
    PLAN_MODE_REPAIR_CONVERSATION,
    PLAN_MODE_RESPONSE_SHA256,
    PLUGIN_STARTUP_NOTICE,
    PLUGIN_STARTUP_PAYLOAD_SHA256,
    PLUGIN_STARTUP_REPAIR_CONVERSATION,
    STARTUP_REPAIR_CONVERSATION,
    STARTUP_REPAIR_ERROR_PREFIX,
    BudgetError,
    PersistentBudget,
    RequestBinding,
    validate_events,
)


def events():
    return [
        {
            "event": "init",
            "init": {"agent": "qve-pit-analyst", "model": "test-model", "tools": ["finish"]},
        },
        {
            "event": "result",
            "result": {"status": "SUCCESS", "structured_output": {"answer": "unavailable"}},
        },
    ]


def check(value, **kwargs):
    return validate_events(value, "qve-pit-analyst", "test-model", **kwargs)


def test_complete_stream_admitted_without_claiming_backend_or_kernel_identity():
    result = check(events())
    assert result["status"] == "PASS"
    assert result["structured_output"] == {"answer": "unavailable"}
    assert result["model_identity"] == "CLI_REPORTED_ONLY"
    assert result["backend_snapshot"] == "UNVERIFIED"
    assert result["preexecution_enforcement"] == "NOT_ESTABLISHED_BY_STREAM_VALIDATION"


@pytest.mark.parametrize(
    "tools",
    [["run_command"], ["finish", "search_web"], None, "finish", [123], ["finish", "finish"]],
)
def test_advertised_tools_fail_even_without_observed_attempts(tools):
    value = events()
    value[0]["init"]["tools"] = tools
    result = check(value)
    assert result["reason"] == "ISOLATION_UNVERIFIED"
    assert result["structured_output"] is None


@pytest.mark.parametrize(
    "key,value,reason",
    [
        ("agent", "default", "AGENT_IDENTITY_MISMATCH"),
        ("model", "different-model", "MODEL_IDENTITY_MISMATCH"),
        ("agent", None, "AGENT_IDENTITY_MISMATCH"),
        ("model", None, "MODEL_IDENTITY_MISMATCH"),
    ],
)
def test_init_identity_is_not_inferred_from_requested_values(key, value, reason):
    stream = events()
    stream[0]["init"][key] = value
    result = check(stream)
    assert result["reason"] == reason
    assert result["structured_output"] is None


@pytest.mark.parametrize(
    "fault",
    [
        "missing_init",
        "duplicate_init",
        "late_init",
        "missing_result",
        "duplicate_result",
        "trailing_step",
        "unknown_event",
        "bad_step",
    ],
)
def test_unknown_or_misordered_events_fail_closed(fault):
    stream = events()
    if fault == "missing_init":
        stream.pop(0)
    elif fault == "duplicate_init":
        stream.insert(1, copy.deepcopy(stream[0]))
    elif fault == "late_init":
        stream.reverse()
    elif fault == "missing_result":
        stream.pop()
    elif fault == "duplicate_result":
        stream.append(copy.deepcopy(stream[-1]))
    elif fault == "trailing_step":
        stream.append({"event": "step_update", "step_update": {"step_type": "message"}})
    elif fault == "unknown_event":
        stream.insert(1, {"event": "new_retrieval_protocol", "data": {}})
    elif fault == "bad_step":
        stream.insert(1, {"event": "step_update", "step_update": None})
    result = check(stream)
    assert result["status"] == "FAIL"
    assert result["structured_output"] is None


@pytest.mark.parametrize(
    "name", ["run_command", "search_web", "view_file", "define_subagent", "unknown"]
)
def test_nested_tool_attempt_discard_terminal_output(name):
    stream = events()
    stream.insert(
        1,
        {
            "event": "step_update",
            "step_update": {"nested": [{"step_type": "tool", "tool_info": {"name": name}}]},
        },
    )
    result = check(stream)
    assert result["reason"] == "PIT_TOOL_ATTEMPT"
    assert result["tool_attempt_count"] == 1
    assert result["structured_output"] is None


def test_only_finish_tool_is_explicitly_allowed():
    stream = events()
    stream.insert(
        1, {"event": "step_update", "step_update": {"step_type": "tool", "tool_name": "finish"}}
    )
    result = check(stream)
    assert result["status"] == "PASS"
    assert result["finish_event_count"] == 1


def test_killed_after_forbidden_init_retains_observed_identity_without_output():
    stream = events()[:1]
    stream[0]["init"]["tools"] = ["run_command"]
    result = check(stream, exit_code=-9)
    assert result["reason"] == "ISOLATION_UNVERIFIED"
    assert result["actual_model"] == "test-model"
    assert result["actual_agent"] == "qve-pit-analyst"
    assert result["advertised_tools"] == ["run_command"]
    assert result["structured_output"] is None


@pytest.mark.parametrize("fault", ["exit", "bool_exit", "partial", "non_object"])
def test_terminal_and_process_must_both_succeed(fault):
    stream = events()
    exit_code = 0
    if fault == "exit":
        exit_code = 1
    elif fault == "bool_exit":
        exit_code = False
    elif fault == "partial":
        stream[-1]["result"]["status"] = "RUNNING"
    else:
        stream[-1]["result"]["structured_output"] = []
    result = check(stream, exit_code=exit_code)
    assert result["status"] == "FAIL"
    assert result["structured_output"] is None


def request():
    return {
        "version": "StockOSAIExplanationRequestV1",
        "ticker": "NVDA",
        "quarter": "FY2027-Q2",
        "source_scope": "current_previous",
        "research_binding": "a" * 64,
        "checkpoint": "2026-10-22T02:24:52+00:00",
        "information_cutoff": "2026-10-22T02:24:52+00:00",
        "source_blocks": [{"paragraph_id": "synthetic", "text": "synthetic evidence"}],
    }


def canonical_sha(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def bound_request():
    value = request()
    binding = RequestBinding.from_request(
        value, expected_request_sha256=canonical_sha(value), expected_research_binding="a" * 64
    )
    return value, binding


def test_request_binding_preserves_exact_input_and_rejects_every_mutation():
    value, binding = bound_request()
    before = copy.deepcopy(value)
    binding.validate_request(value)
    assert value == before
    assert binding.as_dict()["quarter"] == "FY2027-Q2"
    for key, new in (
        ("quarter", "FY2023-Q2"),
        ("ticker", "OTHER"),
        ("research_binding", "b" * 64),
        ("source_blocks", []),
        ("source_scope", "all_research"),
    ):
        changed = copy.deepcopy(value)
        changed[key] = new
        with pytest.raises(ValueError, match="BINDING"):
            binding.validate_request(changed)


def test_frozen_default_binding_does_not_accept_arbitrary_synthetic_request():
    with pytest.raises(ValueError, match="BINDING"):
        RequestBinding.from_request(request())


def test_timezone_free_request_timestamp_is_rejected():
    value = request()
    value["checkpoint"] = "2026-10-22T02:24:52"
    with pytest.raises(ValueError, match="TIMESTAMP"):
        RequestBinding.from_request(
            value, expected_request_sha256=canonical_sha(value), expected_research_binding="a" * 64
        )


def test_budget_reserves_before_return_and_caps_survive_reinstantiation(tmp_path):
    root = tmp_path / "state"
    with PersistentBudget(root, diagnostic_cap=1, research_cap=1) as budget:
        first = budget.reserve("diagnostic", {"synthetic": True})
        assert (root / f"{first}.json").is_file()
        reservation = (root / f"{first}.json").read_bytes()
        budget.finish(first, "COMPLETED")
        assert (root / f"{first}.json").read_bytes() == reservation
    with PersistentBudget(root, diagnostic_cap=1, research_cap=1) as budget:
        assert budget.snapshot()["reserved"] == {"diagnostic": 1, "research": 0}
        with pytest.raises(BudgetError, match="EXHAUSTED"):
            budget.reserve("diagnostic")
        second = budget.reserve("research")
        budget.finish(second, "COMPLETED")
        with pytest.raises(BudgetError, match="EXHAUSTED"):
            budget.reserve("research")


def test_failed_attempt_halts_new_owner_without_reset(tmp_path):
    with PersistentBudget(tmp_path) as budget:
        attempt = budget.reserve("diagnostic")
        budget.finish(attempt, "FAILED", {"reason": "synthetic failure"})
    with PersistentBudget(tmp_path) as budget:
        assert budget.snapshot()["reserved"]["diagnostic"] == 1
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            budget.reserve("research")


def test_unfinished_attempt_halts_without_implicit_retry(tmp_path):
    with PersistentBudget(tmp_path) as budget:
        budget.reserve("diagnostic")
    with PersistentBudget(tmp_path) as budget:
        with pytest.raises(BudgetError, match="UNFINISHED_ATTEMPT"):
            budget.reserve("diagnostic")


def test_foreign_lock_never_stolen_or_removed(tmp_path):
    owner = PersistentBudget(tmp_path)
    owner.acquire()
    original = (tmp_path / "global-active.lock").read_bytes()
    contender = PersistentBudget(tmp_path)
    with pytest.raises(BudgetError, match="ACTIVE_OR_UNVERIFIED_LOCK"):
        contender.acquire()
    with pytest.raises(BudgetError, match="OWNERSHIP_UNVERIFIED"):
        contender.release()
    assert (tmp_path / "global-active.lock").read_bytes() == original
    owner.release()


def test_replaced_lock_is_retained_and_reservation_refused(tmp_path):
    budget = PersistentBudget(tmp_path)
    budget.acquire()
    lock = tmp_path / "global-active.lock"
    lock.write_text('{"owner":"foreign"}')
    with pytest.raises(BudgetError, match="OWNERSHIP_UNVERIFIED"):
        budget.reserve("diagnostic")
    with pytest.raises(BudgetError, match="OWNERSHIP_UNVERIFIED"):
        budget.release()
    assert lock.exists()


@pytest.mark.parametrize("fault", ["delete", "tamper", "orphan"])
def test_journal_tampering_or_crash_gap_cannot_restore_budget(tmp_path, fault):
    with PersistentBudget(tmp_path) as budget:
        attempt = budget.reserve("diagnostic")
        budget.finish(attempt, "COMPLETED")
    reservation = tmp_path / f"{attempt}.json"
    if fault == "delete":
        reservation.unlink()
    elif fault == "tamper":
        reservation.write_text("{}")
    else:
        (tmp_path / "attempt-0002.json").write_text("{}")
    with pytest.raises(BudgetError, match="JOURNAL_MISMATCH"):
        PersistentBudget(tmp_path).acquire()
    assert not (tmp_path / "global-active.lock").exists()


def test_outcomes_are_exclusive_and_cannot_rewrite_failure(tmp_path):
    with PersistentBudget(tmp_path) as budget:
        attempt = budget.reserve("diagnostic")
        budget.finish(attempt, "FAILED")
        original = (tmp_path / f"{attempt}.result.json").read_bytes()
        with pytest.raises(FileExistsError):
            budget.finish(attempt, "COMPLETED")
        assert (tmp_path / f"{attempt}.result.json").read_bytes() == original


def test_budget_policy_cannot_drift_or_increase(tmp_path):
    with PersistentBudget(tmp_path, diagnostic_cap=1, research_cap=1):
        pass
    with pytest.raises(BudgetError, match="POLICY_DRIFT"):
        PersistentBudget(tmp_path).acquire()
    with pytest.raises(BudgetError, match="INVALID_BUDGET_CAP"):
        PersistentBudget(tmp_path / "other", research_cap=23)


def test_symlink_roots_and_journals_refused(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)
    with pytest.raises(BudgetError, match="SYMLINK"):
        PersistentBudget(linked).acquire()
    with PersistentBudget(actual) as budget:
        attempt = budget.reserve("diagnostic")
        budget.finish(attempt, "COMPLETED")
    reservation = actual / f"{attempt}.json"
    target = tmp_path / "reservation-copy"
    target.write_bytes(reservation.read_bytes())
    reservation.unlink()
    reservation.symlink_to(target)
    with pytest.raises(BudgetError, match="SYMLINK"):
        PersistentBudget(actual).acquire()


def eligible_failed_state(tmp_path, *, outcome_status="FAILED", result_changes=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "state"
    result_path = tmp_path / "captured-result.json"
    result = {
        "status": "FAIL",
        "reason": "AGY_NO_EXTERNAL_TOOLS_CONTRACT_UNVERIFIED",
        "structured_output": None,
        "owned_process_group_absent": True,
        "financial_documents_sent": 0,
        "formal_database_writes": 0,
        "global_settings_modified": False,
        "exit_code": -9,
        "actual_agent": "stockos-evidence-reader",
        "actual_model": "gemini-4-argon-high",
        "events": [{"event": "init", "init": {"permission_mode": "always-proceed"}}],
        **(result_changes or {}),
    }
    result_path.write_text(json.dumps(result))
    result_sha = hashlib.sha256(result_path.read_bytes()).hexdigest()
    with PersistentBudget(root) as budget:
        attempt = budget.reserve("diagnostic", {"case": "connection", "synthetic_only": True})
        budget.finish(
            attempt,
            outcome_status,
            {
                "reason": "AGY_NO_EXTERNAL_TOOLS_CONTRACT_UNVERIFIED",
                "result_path": str(result_path),
                "result_sha256": result_sha,
            },
        )
    approval = {
        "version": "StockOSAGYRecoveryApprovalV1",
        "decision": "APPROVED_BY_USER",
        "user_instruction": "Temporarily tighten AGY, verify controls, analyze only after success, restore settings.",
        "policy_hash": "c" * 64,
        "request_sha256": PINNED_REQUEST_SHA256,
        "research_binding": PINNED_RESEARCH_BINDING,
        "attempt_id": attempt,
        "reservation_sha256": hashlib.sha256((root / f"{attempt}.json").read_bytes()).hexdigest(),
        "outcome_sha256": hashlib.sha256(
            (root / f"{attempt}.result.json").read_bytes()
        ).hexdigest(),
        "result_path": str(result_path),
        "result_sha256": result_sha,
    }
    return root, approval


def test_bound_recovery_is_immutable_and_failure_still_counts(tmp_path):
    root, approval = eligible_failed_state(tmp_path)
    original = {p.name: p.read_bytes() for p in root.glob("attempt-*")}
    with PersistentBudget(root) as budget:
        amendment = budget.approve_recovery(approval)
        assert amendment["approval"] == approval
        amendment_raw = (root / "recovery-amendment.json").read_bytes()
        head_raw = (root / "head.json").read_bytes()
        assert budget.approve_recovery(copy.deepcopy(approval)) == amendment
        assert (root / "recovery-amendment.json").read_bytes() == amendment_raw
        assert (root / "head.json").read_bytes() == head_raw
        assert budget.snapshot()["remaining"] == {"diagnostic": 6, "research": 22}
        next_attempt = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        assert next_attempt == "attempt-0002"
        budget.finish(next_attempt, "COMPLETED")
    with PersistentBudget(root) as budget:
        assert budget.snapshot()["reserved"] == {"diagnostic": 2, "research": 0}
        assert budget.snapshot()["recovery"]["policy_hash"] == approval["policy_hash"]
        research_attempt = budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        budget.finish(research_attempt, "COMPLETED")
    assert {name: (root / name).read_bytes() for name in original} == original


@pytest.mark.parametrize(
    "key,value",
    [
        ("version", "different"),
        ("decision", "SELF_APPROVED"),
        ("user_instruction", " "),
        ("policy_hash", None),
        ("policy_hash", "bad"),
        ("request_sha256", "d" * 64),
        ("research_binding", "d" * 64),
        ("attempt_id", "attempt-0002"),
        ("reservation_sha256", "d" * 64),
        ("outcome_sha256", "d" * 64),
        ("result_sha256", "d" * 64),
        ("result_path", "/different-result.json"),
    ],
)
def test_recovery_rejects_unbound_or_wrong_approval_fields(tmp_path, key, value):
    root, approval = eligible_failed_state(tmp_path)
    approval[key] = value
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="RECOVERY"):
            budget.approve_recovery(approval)
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            budget.reserve("diagnostic")
    assert not (root / "recovery-amendment.json").exists()


def test_recovery_requires_owned_lock_and_cannot_raise_limits(tmp_path):
    root, approval = eligible_failed_state(tmp_path)
    budget = PersistentBudget(root)
    with pytest.raises(BudgetError, match="OWNERSHIP"):
        budget.approve_recovery(approval)
    with PersistentBudget(root) as budget:
        approval["diagnostic_cap"] = 8
        with pytest.raises(BudgetError, match="INVALID_RECOVERY_APPROVAL"):
            budget.approve_recovery(approval)
    with pytest.raises(BudgetError, match="INVALID_BUDGET_CAP"):
        PersistentBudget(root, diagnostic_cap=8)
    with pytest.raises(BudgetError, match="BUDGET_POLICY_DRIFT"):
        PersistentBudget(root, diagnostic_cap=6).acquire()


@pytest.mark.parametrize("status", ["ABORTED", "COMPLETED"])
def test_recovery_only_covers_the_approved_failed_outcome(tmp_path, status):
    root, approval = eligible_failed_state(tmp_path, outcome_status=status)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="RECOVERY_OUTCOME_MISMATCH"):
            budget.approve_recovery(approval)


@pytest.mark.parametrize(
    "changes",
    [
        {"financial_documents_sent": 1},
        {"financial_documents_sent": False},
        {"formal_database_writes": 1},
        {"owned_process_group_absent": False},
        {"structured_output": {"partial": True}},
        {"exit_code": 0},
        {"events": [{"event": "init"}, {"event": "result"}]},
        {"actual_model": "another-model"},
        {"global_settings_modified": True},
    ],
)
def test_recovery_does_not_apply_to_other_or_unsafe_failures(tmp_path, changes):
    root, approval = eligible_failed_state(tmp_path, result_changes=changes)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="RECOVERY_RESULT_NOT_ELIGIBLE"):
            budget.approve_recovery(approval)


@pytest.mark.parametrize("metadata", [None, {}, {"policy_hash": "d" * 64}])
def test_after_recovery_every_reservation_must_use_the_approved_policy(tmp_path, metadata):
    root, approval = eligible_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_recovery(approval)
        with pytest.raises(BudgetError, match="RECOVERY_POLICY_MISMATCH"):
            budget.reserve("diagnostic", metadata)
        assert budget.snapshot()["reserved"]["diagnostic"] == 1


def test_a_later_failed_or_unfinished_attempt_is_not_recovered(tmp_path):
    root, approval = eligible_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_recovery(approval)
        next_attempt = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        budget.finish(next_attempt, "FAILED", {"reason": "new failure"})
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        changed = {**approval, "attempt_id": next_attempt}
        with pytest.raises(BudgetError, match="RECOVERY"):
            budget.approve_recovery(changed)
    root2, approval2 = eligible_failed_state(tmp_path / "other")
    with PersistentBudget(root2) as budget:
        budget.approve_recovery(approval2)
        budget.reserve("diagnostic", {"policy_hash": approval2["policy_hash"]})
        with pytest.raises(BudgetError, match="UNFINISHED_ATTEMPT"):
            budget.reserve("research", {"policy_hash": approval2["policy_hash"]})


def test_recovered_failure_never_refunds_diagnostic_or_research_budget(tmp_path):
    root, approval = eligible_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_recovery(approval)
        for _ in range(6):
            attempt = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
            budget.finish(attempt, "COMPLETED")
        with pytest.raises(BudgetError, match="BUDGET_EXHAUSTED"):
            budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        for _ in range(22):
            attempt = budget.reserve("research", {"policy_hash": approval["policy_hash"]})
            budget.finish(attempt, "COMPLETED")
        with pytest.raises(BudgetError, match="BUDGET_EXHAUSTED"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        assert budget.snapshot()["reserved"] == {"diagnostic": 7, "research": 22}


@pytest.mark.parametrize(
    "fault",
    [
        "amendment_deleted",
        "amendment_changed",
        "pin_removed",
        "head_reset",
        "outcome_changed",
        "result_changed",
    ],
)
def test_recovery_evidence_tampering_never_unlocks_new_calls(tmp_path, fault):
    root, approval = eligible_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_recovery(approval)
    if fault == "amendment_deleted":
        (root / "recovery-amendment.json").unlink()
    elif fault == "amendment_changed":
        (root / "recovery-amendment.json").write_text("{}")
    elif fault in ("pin_removed", "head_reset"):
        head = json.loads((root / "head.json").read_text())
        if fault == "pin_removed":
            head.pop("recovery_sha256")
        else:
            head["reservations"] = []
        (root / "head.json").write_text(json.dumps(head))
    elif fault == "outcome_changed":
        (root / "attempt-0001.result.json").write_text("{}")
    else:
        from pathlib import Path

        Path(approval["result_path"]).write_text("{}")
    with pytest.raises(BudgetError, match="RECOVERY|JOURNAL_MISMATCH"):
        PersistentBudget(root).acquire()
    assert not (root / "global-active.lock").exists()


def test_existing_recovery_cannot_be_replaced_by_a_new_policy_or_instruction(tmp_path):
    root, approval = eligible_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_recovery(approval)
        original = (root / "recovery-amendment.json").read_bytes()
        for key, value in (("policy_hash", "d" * 64), ("user_instruction", "different approval")):
            changed = {**approval, key: value}
            with pytest.raises(BudgetError, match="RECOVERY_APPROVAL_CHANGED"):
                budget.approve_recovery(changed)
            assert (root / "recovery-amendment.json").read_bytes() == original


@pytest.mark.parametrize(
    "key,value,reason",
    [
        ("research", 23, "INVALID_BUDGET_CAP"),
        ("diagnostic", True, "INVALID_BUDGET_CAP"),
        ("diagnostic", 6, "BUDGET_POLICY_DRIFT"),
        ("research", 1, "BUDGET_POLICY_DRIFT"),
    ],
)
def test_mutating_public_caps_after_acquire_cannot_change_original_limits(
    tmp_path, key, value, reason
):
    with PersistentBudget(tmp_path) as budget:
        before = (tmp_path / "head.json").read_bytes()
        budget.caps[key] = value
        with pytest.raises(BudgetError, match=reason):
            budget.reserve("diagnostic")
        with pytest.raises(BudgetError, match=reason):
            budget.snapshot()
        assert (tmp_path / "head.json").read_bytes() == before
        assert not list(tmp_path.glob("attempt-*.json"))


def test_disk_budget_policy_is_rechecked_on_each_operation(tmp_path):
    with PersistentBudget(tmp_path) as budget:
        attempt = budget.reserve("diagnostic")
        policy = tmp_path / "budget-policy.json"
        value = json.loads(policy.read_text())
        value["caps"]["research"] = 21
        policy.write_text(json.dumps(value))
        for operation in (
            budget.snapshot,
            lambda: budget.reserve("research"),
            lambda: budget.finish(attempt, "COMPLETED"),
        ):
            with pytest.raises(BudgetError, match="BUDGET_POLICY_DRIFT"):
                operation()
        assert not (tmp_path / f"{attempt}.result.json").exists()


def test_mutated_caps_cannot_create_a_new_policy_before_acquire(tmp_path):
    root = tmp_path / "state"
    budget = PersistentBudget(root)
    budget.caps["research"] = 1
    with pytest.raises(BudgetError, match="BUDGET_POLICY_DRIFT"):
        budget.acquire()
    assert not root.exists()


def startup_failed_state(
    tmp_path,
    *,
    diagnosis_changes=None,
    result_changes=None,
    outcome_status="FAILED",
    use_snapshot=False,
):
    root, original_approval = eligible_failed_state(tmp_path)
    result_path = tmp_path / "second-result.json"
    result = {
        "status": "FAIL",
        "reason": "STREAM_CONTRACT_UNVERIFIED",
        "structured_output": None,
        "owned_process_group_absent": True,
        "permission_mode": "strict",
        "actual_agent": "stockos-evidence-reader",
        "actual_model": "gemini-4-argon-high",
        "policy_hash": original_approval["policy_hash"],
        "exit_code": -9,
        "financial_documents_sent": 0,
        "formal_database_writes": 0,
        "hook_audit": [],
        "denied_tools": [],
        **(result_changes or {}),
    }
    result_path.write_text(json.dumps(result))
    result_sha = hashlib.sha256(result_path.read_bytes()).hexdigest()
    with PersistentBudget(root) as budget:
        budget.approve_recovery(original_approval)
        second = budget.reserve(
            "diagnostic",
            {
                "policy_hash": original_approval["policy_hash"],
                "stage": "filesystem",
                "prompt_sha256": "e" * 64,
            },
        )
        assert second == "attempt-0002"
        budget.finish(
            second,
            outcome_status,
            {
                "policy_hash": original_approval["policy_hash"],
                "reason": "STREAM_CONTRACT_UNVERIFIED",
                "result_path": str(result_path),
                "result_sha256": result_sha,
            },
        )
    source = tmp_path / "conversations" / (STARTUP_REPAIR_CONVERSATION + ".db")
    source.parent.mkdir()
    source.write_bytes(b"Owned synthetic startup source, not a real provider database")
    diagnosis = {
        "version": "StockOSAGYStartupDiagnosisV1",
        "classification": "EXECUTOR_CONSTRUCTION_FAILURE_BEFORE_COMPLETED_MODEL_RESPONSE",
        "conversation_id": STARTUP_REPAIR_CONVERSATION,
        "owned_workspace_confirmed": True,
        "source_database": str(source),
        "source_read_mode": "ro_query_only",
        "source_database_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "steps": [{"index": 0, "type": 14, "status": 3}, {"index": 1, "type": 17, "status": 3}],
        "gen_metadata_rows": 0,
        "executor_metadata_rows": 0,
        "error_payload_sha256": "f" * 64,
        "error_summary": STARTUP_REPAIR_ERROR_PREFIX,
        "inference_dispatch": "NO_COMPLETED_GENERATION_METADATA_NOT_INDEPENDENT_BACKEND_ATTESTATION",
        "formal_database_writes": 0,
        "financial_documents_sent": 0,
        "settings_and_hooks_restored": True,
        **(diagnosis_changes or {}),
    }
    if use_snapshot:
        snapshot = tmp_path / "owned-startup-snapshot.sqlite"
        snapshot.write_bytes(b"Frozen consistent synthetic startup source snapshot")
        diagnosis.update(
            source_snapshot_path=str(snapshot),
            source_snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        )
    diagnosis_path = tmp_path / "startup-diagnosis.json"
    diagnosis_path.write_text(json.dumps(diagnosis))
    approval = {
        "version": "StockOSAGYStartupRepairApprovalV1",
        "decision": "APPROVED_BY_USER",
        "user_instruction": original_approval["user_instruction"],
        "policy_hash": "d" * 64,
        "request_sha256": PINNED_REQUEST_SHA256,
        "research_binding": PINNED_RESEARCH_BINDING,
        "attempt_id": second,
        "reservation_sha256": hashlib.sha256((root / f"{second}.json").read_bytes()).hexdigest(),
        "outcome_sha256": hashlib.sha256((root / f"{second}.result.json").read_bytes()).hexdigest(),
        "result_path": str(result_path),
        "result_sha256": result_sha,
        "diagnosis_path": str(diagnosis_path),
        "diagnosis_sha256": hashlib.sha256(diagnosis_path.read_bytes()).hexdigest(),
        "prior_recovery_sha256": hashlib.sha256(
            (root / "recovery-amendment.json").read_bytes()
        ).hexdigest(),
    }
    return root, original_approval, approval


def test_startup_repair_appends_a_new_policy_without_rewriting_failed_history(tmp_path):
    root, original, approval = startup_failed_state(tmp_path)
    protected = {
        path.name: path.read_bytes()
        for path in [*root.glob("attempt-*.json"), root / "recovery-amendment.json"]
    }
    with PersistentBudget(root) as budget:
        amendment = budget.approve_startup_repair(approval)
        assert amendment["approval"] == approval
        raw = (root / "startup-repair-amendment.json").read_bytes()
        assert budget.approve_startup_repair(copy.deepcopy(approval)) == amendment
        assert (root / "startup-repair-amendment.json").read_bytes() == raw
        snapshot = budget.snapshot()
        assert snapshot["remaining"] == {"diagnostic": 5, "research": 22}
        assert snapshot["active_policy_hash"] == approval["policy_hash"]
        assert snapshot["recovery"]["policy_hash"] == original["policy_hash"]
        assert snapshot["startup_repair"]["attempt_id"] == "attempt-0002"
        for policy in (None, original["policy_hash"], "e" * 64):
            with pytest.raises(BudgetError, match="RECOVERY_POLICY_MISMATCH"):
                budget.reserve("diagnostic", {"policy_hash": policy})
        attempt = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        assert attempt == "attempt-0003"
        budget.finish(attempt, "COMPLETED")
    with PersistentBudget(root) as budget:
        assert budget.snapshot()["reserved"] == {"diagnostic": 3, "research": 0}
        attempt = budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        budget.finish(attempt, "COMPLETED")
    assert {name: (root / name).read_bytes() for name in protected} == protected


@pytest.mark.parametrize(
    "field,value",
    [
        ("decision", "AUTO_APPROVED"),
        ("user_instruction", "different instruction"),
        ("policy_hash", "c" * 64),
        ("policy_hash", None),
        ("attempt_id", "attempt-0003"),
        ("request_sha256", "e" * 64),
        ("research_binding", "e" * 64),
        ("reservation_sha256", "e" * 64),
        ("outcome_sha256", "e" * 64),
        ("result_sha256", "e" * 64),
        ("diagnosis_sha256", "e" * 64),
        ("prior_recovery_sha256", "e" * 64),
    ],
)
def test_startup_repair_rejects_any_unbound_approval_component(tmp_path, field, value):
    root, original, approval = startup_failed_state(tmp_path)
    approval[field] = value
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="STARTUP_REPAIR"):
            budget.approve_startup_repair(approval)
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            budget.reserve("diagnostic", {"policy_hash": original["policy_hash"]})
    assert not (root / "startup-repair-amendment.json").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"steps": [{"index": 0, "type": 14, "status": 3}, {"index": 1, "type": 2, "status": 3}]},
        {
            "steps": [
                {"index": False, "type": 14, "status": 3},
                {"index": 1, "type": 17, "status": 3},
            ]
        },
        {"gen_metadata_rows": 1},
        {"executor_metadata_rows": 1},
        {"gen_metadata_rows": False},
        {"owned_workspace_confirmed": False},
        {"source_read_mode": "writable"},
        {"error_summary": "arbitrary timeout or runtime exception"},
        {"error_summary": 'failed to construct executor: unknown component: tool "different_tool"'},
        {"conversation_id": "unowned-conversation"},
        {"settings_and_hooks_restored": False},
        {"financial_documents_sent": 1},
        {"formal_database_writes": 1},
        {"source_database_sha256": "e" * 64},
    ],
)
def test_startup_repair_is_not_a_generic_exception_or_data_retry(tmp_path, changes):
    root, _, approval = startup_failed_state(tmp_path, diagnosis_changes=changes)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="STARTUP_REPAIR"):
            budget.approve_startup_repair(approval)


@pytest.mark.parametrize(
    "changes",
    [
        {"financial_documents_sent": 1},
        {"formal_database_writes": 1},
        {"owned_process_group_absent": False},
        {"permission_mode": "always-proceed"},
        {"structured_output": {"already_ran": True}},
        {"hook_audit": [{"event": "invocation"}]},
        {"reason": "TIMEOUT"},
    ],
)
def test_startup_repair_requires_the_exact_pre_executor_failed_result(tmp_path, changes):
    root, _, approval = startup_failed_state(tmp_path, result_changes=changes)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="STARTUP_REPAIR_RESULT_NOT_ELIGIBLE"):
            budget.approve_startup_repair(approval)


@pytest.mark.parametrize("status", ["COMPLETED", "ABORTED"])
def test_startup_repair_cannot_reclassify_other_outcome_statuses(tmp_path, status):
    root, _, approval = startup_failed_state(tmp_path, outcome_status=status)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="STARTUP_REPAIR_OUTCOME_MISMATCH"):
            budget.approve_startup_repair(approval)


def test_startup_repair_does_not_allow_an_unfinished_or_third_failure(tmp_path):
    root, _, approval = startup_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_startup_repair(approval)
        attempt = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        budget.finish(attempt, "FAILED", {"reason": "later failure"})
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        with pytest.raises(BudgetError, match="STARTUP_REPAIR"):
            budget.approve_startup_repair({**approval, "attempt_id": attempt})
    second_root, _, second_approval = startup_failed_state(tmp_path / "unfinished")
    (second_root / "attempt-0002.result.json").unlink()
    with PersistentBudget(second_root) as budget:
        with pytest.raises(BudgetError, match="STARTUP_REPAIR_OUTCOME_MISSING"):
            budget.approve_startup_repair(second_approval)


def test_startup_repair_preserves_the_original_seven_and_twenty_two_limits(tmp_path):
    root, _, approval = startup_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_startup_repair(approval)
        for _ in range(5):
            attempt = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
            budget.finish(attempt, "COMPLETED")
        with pytest.raises(BudgetError, match="BUDGET_EXHAUSTED"):
            budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        for _ in range(22):
            attempt = budget.reserve("research", {"policy_hash": approval["policy_hash"]})
            budget.finish(attempt, "COMPLETED")
        with pytest.raises(BudgetError, match="BUDGET_EXHAUSTED"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        assert budget.snapshot()["reserved"] == {"diagnostic": 7, "research": 22}


@pytest.mark.parametrize(
    "fault", ["deleted", "changed", "pin_removed", "diagnosis_changed", "snapshot_changed"]
)
def test_startup_extension_and_diagnosis_tampering_fail_closed(tmp_path, fault):
    root, _, approval = startup_failed_state(tmp_path, use_snapshot=True)
    with PersistentBudget(root) as budget:
        budget.approve_startup_repair(approval)
    if fault == "deleted":
        (root / "startup-repair-amendment.json").unlink()
    elif fault == "changed":
        (root / "startup-repair-amendment.json").write_text("{}")
    elif fault == "pin_removed":
        head = json.loads((root / "head.json").read_text())
        head.pop("startup_repair_sha256")
        (root / "head.json").write_text(json.dumps(head))
    elif fault == "diagnosis_changed":
        from pathlib import Path

        Path(approval["diagnosis_path"]).write_text("{}")
    else:
        (tmp_path / "owned-startup-snapshot.sqlite").write_bytes(b"changed")
    with pytest.raises(BudgetError, match="STARTUP_REPAIR"):
        PersistentBudget(root).acquire()
    assert not (root / "global-active.lock").exists()


def test_frozen_snapshot_avoids_dependence_on_provider_database_housekeeping(tmp_path):
    root, _, approval = startup_failed_state(tmp_path, use_snapshot=True)
    with PersistentBudget(root) as budget:
        budget.approve_startup_repair(approval)
    source = tmp_path / "conversations" / (STARTUP_REPAIR_CONVERSATION + ".db")
    source.write_bytes(b"later provider housekeeping")
    with PersistentBudget(root) as budget:
        assert budget.snapshot()["remaining"]["diagnostic"] == 5


def test_startup_repair_cannot_change_its_policy_or_add_caps_after_creation(tmp_path):
    root, _, approval = startup_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_startup_repair(approval)
        raw = (root / "startup-repair-amendment.json").read_bytes()
        with pytest.raises(BudgetError, match="STARTUP_REPAIR_APPROVAL_CHANGED"):
            budget.approve_startup_repair({**approval, "policy_hash": "e" * 64})
        with pytest.raises(BudgetError, match="INVALID_STARTUP_REPAIR_APPROVAL"):
            budget.approve_startup_repair({**approval, "diagnostic_cap": 8})
        assert (root / "startup-repair-amendment.json").read_bytes() == raw


def plugin_startup_failed_state(
    tmp_path, *, diagnosis_changes=None, result_changes=None, outcome_status="FAILED"
):
    root, original, previous = startup_failed_state(tmp_path, use_snapshot=True)
    evidence = tmp_path / "third-startup"
    evidence.mkdir()
    result_path = evidence / "result.json"
    result = {
        "status": "FAIL",
        "reason": "STREAM_CONTRACT_UNVERIFIED",
        "structured_output": None,
        "owned_process_group_absent": True,
        "permission_mode": "strict",
        "actual_agent": "stockos-evidence-reader",
        "actual_model": "gemini-4-argon-high",
        "policy_hash": previous["policy_hash"],
        "exit_code": -9,
        "financial_documents_sent": 0,
        "formal_database_writes": 0,
        "denied_tools": [],
        "tool_completion_metadata": [],
        "hook_audit": [
            {
                "event": "session",
                "configuration_matches": True,
                "conversation_id": PLUGIN_STARTUP_REPAIR_CONVERSATION,
                "model_name": "gemini-4-argon-high",
                "nonce": "a" * 32,
                "workspaces": [str(tmp_path / "owned-workspace")],
                "invocation_number": None,
                "step_index": None,
                "tool_name": None,
            }
        ],
        "stream_events": [
            {
                "event": "init",
                "init": {
                    "agent": "stockos-evidence-reader",
                    "model": "gemini-4-argon-high",
                    "permission_mode": "strict",
                },
            },
            {
                "event": "step_update",
                "step_state": "DONE",
                "step_type": "user_input",
                "tool_events": [],
            },
            {
                "event": "step_update",
                "step_state": "DONE",
                "step_type": "unknown",
                "tool_events": [],
            },
        ],
        **(result_changes or {}),
    }
    result_path.write_text(json.dumps(result))
    result_sha = hashlib.sha256(result_path.read_bytes()).hexdigest()
    with PersistentBudget(root) as budget:
        budget.approve_startup_repair(previous)
        attempt = budget.reserve(
            "diagnostic", {"policy_hash": previous["policy_hash"], "stage": "filesystem"}
        )
        assert attempt == "attempt-0003"
        budget.finish(
            attempt,
            outcome_status,
            {
                "policy_hash": previous["policy_hash"],
                "reason": "STREAM_CONTRACT_UNVERIFIED",
                "result_path": str(result_path),
                "result_sha256": result_sha,
            },
        )
    snapshot = evidence / "owned-startup-snapshot.sqlite"
    snapshot.write_bytes(b"Synthetic consistent owned third startup snapshot")
    diagnosis = {
        "version": "StockOSAGYPluginStartupDiagnosisV1",
        "classification": "PLUGIN_INITIALIZATION_NOTICE_BEFORE_PRE_INVOCATION",
        "conversation_id": PLUGIN_STARTUP_REPAIR_CONVERSATION,
        "owned_workspace_confirmed": True,
        "source_database": str(
            tmp_path / "conversations" / (PLUGIN_STARTUP_REPAIR_CONVERSATION + ".db")
        ),
        "source_read_mode": "ro_query_only",
        "steps": [{"index": 0, "type": 14, "status": 3}, {"index": 1, "type": 90, "status": 3}],
        "installed_binary_enum_type_90": "CORTEX_STEP_TYPE_EPHEMERAL_MESSAGE",
        "gen_metadata_rows": 0,
        "executor_metadata_rows": 0,
        "error_payload_sha256": PLUGIN_STARTUP_PAYLOAD_SHA256,
        "notice_summary": PLUGIN_STARTUP_NOTICE,
        "session_hook_loaded": True,
        "pre_invocation_observed": False,
        "inference_dispatch": "NO_COMPLETED_GENERATION_METADATA_NOT_INDEPENDENT_BACKEND_ATTESTATION",
        "formal_database_writes": 0,
        "financial_documents_sent": 0,
        "settings_and_hooks_restored": True,
        "source_snapshot_path": str(snapshot),
        "source_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        **(diagnosis_changes or {}),
    }
    diagnosis_path = evidence / "startup-diagnosis.json"
    diagnosis_path.write_text(json.dumps(diagnosis))
    approval = {
        "version": "StockOSAGYPluginStartupRepairApprovalV1",
        "decision": "APPROVED_BY_USER",
        "user_instruction": original["user_instruction"],
        "policy_hash": "e" * 64,
        "request_sha256": PINNED_REQUEST_SHA256,
        "research_binding": PINNED_RESEARCH_BINDING,
        "attempt_id": attempt,
        "reservation_sha256": hashlib.sha256((root / f"{attempt}.json").read_bytes()).hexdigest(),
        "outcome_sha256": hashlib.sha256(
            (root / f"{attempt}.result.json").read_bytes()
        ).hexdigest(),
        "result_path": str(result_path),
        "result_sha256": result_sha,
        "diagnosis_path": str(diagnosis_path),
        "diagnosis_sha256": hashlib.sha256(diagnosis_path.read_bytes()).hexdigest(),
        "prior_startup_repair_sha256": hashlib.sha256(
            (root / "startup-repair-amendment.json").read_bytes()
        ).hexdigest(),
    }
    return root, original, previous, approval


def test_plugin_startup_repair_retains_all_failures_and_binds_only_the_new_policy(tmp_path):
    root, original, previous, approval = plugin_startup_failed_state(tmp_path)
    protected = {
        p.name: p.read_bytes()
        for p in [
            *root.glob("attempt-*.json"),
            root / "recovery-amendment.json",
            root / "startup-repair-amendment.json",
        ]
    }
    with PersistentBudget(root) as budget:
        amendment = budget.approve_plugin_startup_repair(approval)
        assert budget.approve_plugin_startup_repair(copy.deepcopy(approval)) == amendment
        snapshot = budget.snapshot()
        assert snapshot["remaining"] == {"diagnostic": 4, "research": 22}
        assert snapshot["reserved"] == {"diagnostic": 3, "research": 0}
        assert snapshot["active_policy_hash"] == approval["policy_hash"]
        assert snapshot["plugin_startup_repair"]["attempt_id"] == "attempt-0003"
        for policy in (None, original["policy_hash"], previous["policy_hash"], "f" * 64):
            with pytest.raises(BudgetError, match="RECOVERY_POLICY_MISMATCH"):
                budget.reserve("diagnostic", {"policy_hash": policy})
        attempt = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        assert attempt == "attempt-0004"
        budget.finish(attempt, "COMPLETED")
    with PersistentBudget(root) as budget:
        assert budget.snapshot()["active_policy_hash"] == approval["policy_hash"]
    assert {name: (root / name).read_bytes() for name in protected} == protected


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "generic-retry"),
        ("decision", "AUTO_APPROVED"),
        ("user_instruction", ""),
        ("user_instruction", "changed instruction"),
        ("policy_hash", "d" * 64),
        ("policy_hash", "c" * 64),
        ("policy_hash", None),
        ("attempt_id", "attempt-0004"),
        ("request_sha256", "a" * 64),
        ("research_binding", "a" * 64),
        ("reservation_sha256", "a" * 64),
        ("outcome_sha256", "a" * 64),
        ("result_sha256", "a" * 64),
        ("diagnosis_sha256", "a" * 64),
        ("prior_startup_repair_sha256", "a" * 64),
        ("result_path", "relative.json"),
        ("diagnosis_path", "relative.json"),
    ],
)
def test_plugin_startup_repair_requires_every_exact_binding(tmp_path, field, value):
    root, _, previous, approval = plugin_startup_failed_state(tmp_path)
    approval[field] = value
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="STARTUP_REPAIR"):
            budget.approve_plugin_startup_repair(approval)
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            budget.reserve("research", {"policy_hash": previous["policy_hash"]})
    assert not (root / "plugin-startup-repair-amendment.json").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"classification": "RUNTIME_ERROR"},
        {"conversation_id": "unowned"},
        {"owned_workspace_confirmed": False},
        {"source_read_mode": "writable"},
        {"steps": [{"index": 0, "type": 14, "status": 3}, {"index": 1, "type": 17, "status": 3}]},
        {
            "steps": [
                {"index": False, "type": 14, "status": 3},
                {"index": 1, "type": 90, "status": 3},
            ]
        },
        {"gen_metadata_rows": 1},
        {"executor_metadata_rows": 1},
        {"gen_metadata_rows": False},
        {"installed_binary_enum_type_90": "UNKNOWN"},
        {"notice_summary": "another plugin failure"},
        {"error_payload_sha256": "a" * 64},
        {"session_hook_loaded": False},
        {"pre_invocation_observed": True},
        {"financial_documents_sent": 1},
        {"formal_database_writes": 1},
        {"settings_and_hooks_restored": False},
        {"source_snapshot_path": None},
        {"source_snapshot_sha256": "a" * 64},
    ],
)
def test_plugin_startup_repair_is_not_a_generic_runtime_or_research_retry(tmp_path, changes):
    root, _, _, approval = plugin_startup_failed_state(tmp_path, diagnosis_changes=changes)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="PLUGIN_STARTUP_REPAIR"):
            budget.approve_plugin_startup_repair(approval)


@pytest.mark.parametrize(
    "changes",
    [
        {"financial_documents_sent": 1},
        {"formal_database_writes": 1},
        {"permission_mode": "always-proceed"},
        {"structured_output": {"completed": True}},
        {"owned_process_group_absent": False},
        {"exit_code": False},
        {"hook_audit": []},
        {"hook_audit": [{"event": "invocation"}]},
        {"stream_events": []},
        {"denied_tools": ["view_file"]},
        {"tool_completion_metadata": [{"tool_name": "view_file"}]},
    ],
)
def test_plugin_startup_repair_requires_session_only_and_no_completed_content(tmp_path, changes):
    root, _, _, approval = plugin_startup_failed_state(tmp_path, result_changes=changes)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="PLUGIN_STARTUP_REPAIR_RESULT_NOT_ELIGIBLE"):
            budget.approve_plugin_startup_repair(approval)


@pytest.mark.parametrize("status", ["COMPLETED", "ABORTED"])
def test_plugin_startup_repair_cannot_reclassify_outcomes(tmp_path, status):
    root, _, _, approval = plugin_startup_failed_state(tmp_path, outcome_status=status)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="PLUGIN_STARTUP_REPAIR_OUTCOME_MISMATCH"):
            budget.approve_plugin_startup_repair(approval)


def test_plugin_startup_repair_does_not_recover_a_fourth_failure_or_unfinished_attempt(tmp_path):
    root, _, _, approval = plugin_startup_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_plugin_startup_repair(approval)
        fourth = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        with pytest.raises(BudgetError, match="UNFINISHED_ATTEMPT"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        budget.finish(fourth, "FAILED", {"reason": "another startup or runtime failure"})
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        with pytest.raises(BudgetError, match="INVALID_PLUGIN_STARTUP_REPAIR_APPROVAL"):
            budget.approve_plugin_startup_repair({**approval, "attempt_id": fourth})


def test_plugin_startup_repair_keeps_exact_seven_and_twenty_two_caps(tmp_path):
    root, _, _, approval = plugin_startup_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_plugin_startup_repair(approval)
        for _ in range(4):
            attempt = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
            budget.finish(attempt, "COMPLETED")
        with pytest.raises(BudgetError, match="BUDGET_EXHAUSTED"):
            budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        for _ in range(22):
            attempt = budget.reserve("research", {"policy_hash": approval["policy_hash"]})
            budget.finish(attempt, "COMPLETED")
        with pytest.raises(BudgetError, match="BUDGET_EXHAUSTED"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        assert budget.snapshot()["reserved"] == {"diagnostic": 7, "research": 22}


@pytest.mark.parametrize(
    "fault",
    [
        "deleted",
        "changed",
        "pin_removed",
        "prior_changed",
        "diagnosis_changed",
        "snapshot_changed",
        "result_changed",
    ],
)
def test_plugin_startup_chain_tamper_fails_closed_on_reacquire(tmp_path, fault):
    root, _, _, approval = plugin_startup_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_plugin_startup_repair(approval)
    if fault == "deleted":
        (root / "plugin-startup-repair-amendment.json").unlink()
    elif fault == "changed":
        (root / "plugin-startup-repair-amendment.json").write_text("{}")
    elif fault == "pin_removed":
        head = json.loads((root / "head.json").read_text())
        head.pop("plugin_startup_repair_sha256")
        (root / "head.json").write_text(json.dumps(head))
    elif fault == "prior_changed":
        (root / "startup-repair-amendment.json").write_text("{}")
    elif fault == "diagnosis_changed":
        Path(approval["diagnosis_path"]).write_text("{}")
    elif fault == "result_changed":
        Path(approval["result_path"]).write_text("{}")
    else:
        (tmp_path / "third-startup" / "owned-startup-snapshot.sqlite").write_bytes(b"changed")
    with pytest.raises(BudgetError, match="STARTUP_REPAIR"):
        PersistentBudget(root).acquire()
    assert not (root / "global-active.lock").exists()


def test_plugin_startup_repair_requires_owned_lock_and_cannot_change_its_decision(tmp_path):
    root, _, _, approval = plugin_startup_failed_state(tmp_path)
    with pytest.raises(BudgetError, match="LOCK_OWNERSHIP_UNVERIFIED"):
        PersistentBudget(root).approve_plugin_startup_repair(approval)
    with PersistentBudget(root) as budget:
        budget.approve_plugin_startup_repair(approval)
        raw = (root / "plugin-startup-repair-amendment.json").read_bytes()
        with pytest.raises(BudgetError, match="PLUGIN_STARTUP_REPAIR_APPROVAL_CHANGED"):
            budget.approve_plugin_startup_repair({**approval, "policy_hash": "f" * 64})
        with pytest.raises(BudgetError, match="INVALID_PLUGIN_STARTUP_REPAIR_APPROVAL"):
            budget.approve_plugin_startup_repair({**approval, "diagnostic_cap": 8})
        assert (root / "plugin-startup-repair-amendment.json").read_bytes() == raw


def denial_protocol_failed_state(
    tmp_path, *, diagnosis_changes=None, result_changes=None, outcome_status="FAILED"
):
    root, original, _, previous = plugin_startup_failed_state(tmp_path)
    evidence = tmp_path / "fourth-protocol"
    evidence.mkdir()
    result_path = evidence / "result.json"
    common_audit = {
        "configuration_matches": True,
        "conversation_id": DENIAL_PROTOCOL_REPAIR_CONVERSATION,
        "model_name": "gemini-4-argon-high",
        "nonce": "b" * 32,
        "workspaces": [str(tmp_path / "owned-fourth-workspace")],
        "invocation_number": None,
        "step_index": None,
        "tool_name": None,
        "args_sha256": hashlib.sha256(b"{}").hexdigest(),
    }
    result = json.loads(Path(previous["result_path"]).read_bytes())
    result.update(
        {
            "policy_hash": previous["policy_hash"],
            "hook_audit": [
                {**common_audit, "event": "session"},
                {**common_audit, "event": "invocation", "invocation_number": 0, "blocked": False},
                {
                    **common_audit,
                    "event": "pre",
                    "decision": "deny",
                    "tool_name": "view_file",
                    "step_index": 2,
                    "args_sha256": DENIAL_PROTOCOL_ARGS_SHA256,
                },
            ],
            "stream_events": [
                result["stream_events"][0],
                {
                    "event": "step_update",
                    "step_state": "DONE",
                    "step_type": "user_input",
                    "tool_events": [],
                },
                {
                    "event": "step_update",
                    "step_state": "DONE",
                    "step_type": "agent_response",
                    "tool_events": [],
                },
                {
                    "event": "step_update",
                    "step_state": "ACTIVE",
                    "step_type": "tool",
                    "tool_events": [{"state": "ACTIVE", "tool_name": "view_file"}],
                },
                {
                    "event": "step_update",
                    "step_state": "ERROR",
                    "step_type": "tool",
                    "tool_events": [{"state": "ERROR", "tool_name": "view_file"}],
                },
            ],
            **(result_changes or {}),
        }
    )
    result_path.write_text(json.dumps(result))
    result_sha = hashlib.sha256(result_path.read_bytes()).hexdigest()
    with PersistentBudget(root) as budget:
        budget.approve_plugin_startup_repair(previous)
        attempt = budget.reserve(
            "diagnostic",
            {"policy_hash": previous["policy_hash"], "stage": "filesystem_command_and_write"},
        )
        assert attempt == "attempt-0004"
        budget.finish(
            attempt,
            outcome_status,
            {
                "policy_hash": previous["policy_hash"],
                "reason": "STREAM_CONTRACT_UNVERIFIED",
                "result_path": str(result_path),
                "result_sha256": result_sha,
            },
        )
    snapshot = evidence / "owned-protocol-snapshot.sqlite"
    snapshot.write_bytes(b"Synthetic owned fourth protocol snapshot; one synthetic generation")
    diagnosis = {
        "version": "StockOSAGYDenialProtocolDiagnosisV1",
        "classification": "PINNED_PRE_TOOL_DENIAL_ERROR_STATE_REJECTED_BY_ADAPTER",
        "conversation_id": DENIAL_PROTOCOL_REPAIR_CONVERSATION,
        "owned_workspace_confirmed": True,
        "source_database": str(
            tmp_path / "conversations" / (DENIAL_PROTOCOL_REPAIR_CONVERSATION + ".db")
        ),
        "source_read_mode": "ro_query_only",
        "steps": [
            {"index": 0, "type": 14, "status": 3},
            {"index": 1, "type": 15, "status": 3},
            {"index": 2, "type": 132, "status": 7},
            {"index": 3, "type": 132, "status": 2},
            {"index": 4, "type": 132, "status": 1},
        ],
        "gen_metadata_rows": 1,
        "executor_metadata_rows": 0,
        "inference_scope": "ONE_COMPLETED_SYNTHETIC_GENERATION; NO_FINANCIAL_DOCUMENTS",
        "blocked_tool_name": "view_file",
        "blocked_step_index": 2,
        "blocked_args_sha256": DENIAL_PROTOCOL_ARGS_SHA256,
        "error_details_sha256": DENIAL_PROTOCOL_ERROR_SHA256,
        "denial_message": DENIAL_PROTOCOL_MESSAGE,
        "source_snapshot_path": str(snapshot),
        "source_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "formal_database_writes": 0,
        "financial_documents_sent": 0,
        "settings_hooks_plugins_restored": True,
        "pre_invocation_observed": True,
        "post_tool_hook_observed": False,
        "stream_terminal_state": "ERROR",
        "stream_error_type": "informational only; not denial authority",
        **(diagnosis_changes or {}),
    }
    diagnosis_path = evidence / "protocol-diagnosis.json"
    diagnosis_path.write_text(json.dumps(diagnosis))
    approval = {
        "version": "StockOSAGYDenialProtocolRepairApprovalV1",
        "decision": "APPROVED_BY_USER",
        "user_instruction": original["user_instruction"],
        "policy_hash": "f" * 64,
        "request_sha256": PINNED_REQUEST_SHA256,
        "research_binding": PINNED_RESEARCH_BINDING,
        "attempt_id": attempt,
        "reservation_sha256": hashlib.sha256((root / f"{attempt}.json").read_bytes()).hexdigest(),
        "outcome_sha256": hashlib.sha256(
            (root / f"{attempt}.result.json").read_bytes()
        ).hexdigest(),
        "result_path": str(result_path),
        "result_sha256": result_sha,
        "diagnosis_path": str(diagnosis_path),
        "diagnosis_sha256": hashlib.sha256(diagnosis_path.read_bytes()).hexdigest(),
        "prior_plugin_startup_repair_sha256": hashlib.sha256(
            (root / "plugin-startup-repair-amendment.json").read_bytes()
        ).hexdigest(),
    }
    return root, original, previous, approval


def test_denial_protocol_repair_retains_four_failures_and_one_synthetic_generation(tmp_path):
    root, _, previous, approval = denial_protocol_failed_state(tmp_path)
    protected = {p.name: p.read_bytes() for p in root.glob("*.json") if p.name != "head.json"}
    with PersistentBudget(root) as budget:
        amendment = budget.approve_denial_protocol_repair(approval)
        assert budget.approve_denial_protocol_repair(copy.deepcopy(approval)) == amendment
        snapshot = budget.snapshot()
        assert snapshot["remaining"] == {"diagnostic": 3, "research": 22}
        assert snapshot["reserved"] == {"diagnostic": 4, "research": 0}
        assert snapshot["denial_protocol_repair"]["attempt_id"] == "attempt-0004"
        assert snapshot["active_policy_hash"] == approval["policy_hash"]
        for policy in (None, previous["policy_hash"], "a" * 64):
            with pytest.raises(BudgetError, match="RECOVERY_POLICY_MISMATCH"):
                budget.reserve("diagnostic", {"policy_hash": policy})
        fifth = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        assert fifth == "attempt-0005"
        budget.finish(fifth, "COMPLETED")
    with PersistentBudget(root) as budget:
        assert budget.snapshot()["active_policy_hash"] == approval["policy_hash"]
    assert {n: (root / n).read_bytes() for n in protected} == protected
    assert json.loads(Path(approval["diagnosis_path"]).read_bytes())["gen_metadata_rows"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "generic-retry"),
        ("decision", "AUTO_APPROVED"),
        ("user_instruction", ""),
        ("user_instruction", "changed instruction"),
        ("policy_hash", "c" * 64),
        ("policy_hash", "d" * 64),
        ("policy_hash", "e" * 64),
        ("policy_hash", None),
        ("attempt_id", "attempt-0005"),
        ("request_sha256", "a" * 64),
        ("research_binding", "a" * 64),
        ("reservation_sha256", "a" * 64),
        ("outcome_sha256", "a" * 64),
        ("result_sha256", "a" * 64),
        ("diagnosis_sha256", "a" * 64),
        ("prior_plugin_startup_repair_sha256", "a" * 64),
        ("result_path", "relative.json"),
        ("diagnosis_path", "relative.json"),
    ],
)
def test_denial_protocol_repair_rejects_unbound_approval(tmp_path, field, value):
    root, _, previous, approval = denial_protocol_failed_state(tmp_path)
    approval[field] = value
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="REPAIR"):
            budget.approve_denial_protocol_repair(approval)
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            budget.reserve("research", {"policy_hash": previous["policy_hash"]})
    assert not (root / "denial-protocol-repair-amendment.json").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"classification": "ARBITRARY_RUNTIME_FAILURE"},
        {"conversation_id": "unowned"},
        {"owned_workspace_confirmed": False},
        {"source_read_mode": "writable"},
        {"steps": [{"index": 0, "type": 14, "status": 3}, {"index": 1, "type": 17, "status": 3}]},
        {"gen_metadata_rows": 0},
        {"gen_metadata_rows": True},
        {"gen_metadata_rows": 2},
        {"executor_metadata_rows": 1},
        {"inference_scope": "NO_INFERENCE"},
        {"blocked_tool_name": "run_command"},
        {"blocked_step_index": 3},
        {"blocked_step_index": True},
        {"blocked_args_sha256": "a" * 64},
        {"error_details_sha256": "a" * 64},
        {"denial_message": "permission denied"},
        {"denial_message": DENIAL_PROTOCOL_MESSAGE + " modified"},
        {"financial_documents_sent": 1},
        {"formal_database_writes": 1},
        {"settings_hooks_plugins_restored": False},
        {"pre_invocation_observed": False},
        {"post_tool_hook_observed": True},
        {"stream_terminal_state": "DONE"},
        {"source_snapshot_path": None},
        {"source_snapshot_sha256": "a" * 64},
    ],
)
def test_denial_protocol_repair_accepts_only_the_exact_synthetic_adapter_mismatch(
    tmp_path, changes
):
    root, _, _, approval = denial_protocol_failed_state(tmp_path, diagnosis_changes=changes)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="DENIAL_PROTOCOL_REPAIR"):
            budget.approve_denial_protocol_repair(approval)


@pytest.mark.parametrize(
    "changes",
    [
        {"financial_documents_sent": 1},
        {"formal_database_writes": 1},
        {"permission_mode": "always-proceed"},
        {"structured_output": {"candidate": True}},
        {"owned_process_group_absent": False},
        {"exit_code": False},
        {"hook_audit": []},
        {"stream_events": []},
        {"denied_tools": ["view_file"]},
        {"tool_completion_metadata": [{"tool_name": "view_file"}]},
    ],
)
def test_denial_protocol_repair_rejects_content_or_incomplete_boundary_proof(tmp_path, changes):
    root, _, _, approval = denial_protocol_failed_state(tmp_path, result_changes=changes)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="DENIAL_PROTOCOL_REPAIR_RESULT_NOT_ELIGIBLE"):
            budget.approve_denial_protocol_repair(approval)


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_nonce",
        "wrong_workspace",
        "wrong_conversation",
        "config_drift",
        "blocked_invocation",
        "boolean_invocation",
        "wrong_step",
        "wrong_args",
        "allowed_pre",
        "post_present",
        "tool_succeeded",
    ],
)
def test_denial_protocol_repair_requires_the_exact_trusted_pre_and_error(tmp_path, fault):
    root, _, _, approval = denial_protocol_failed_state(tmp_path)
    result_path = Path(approval["result_path"])
    result = json.loads(result_path.read_bytes())
    if fault == "wrong_nonce":
        result["hook_audit"][2]["nonce"] = "c" * 32
    elif fault == "wrong_workspace":
        result["hook_audit"][2]["workspaces"] = ["/unowned"]
    elif fault == "wrong_conversation":
        result["hook_audit"][2]["conversation_id"] = "other"
    elif fault == "config_drift":
        result["hook_audit"][2]["configuration_matches"] = False
    elif fault == "blocked_invocation":
        result["hook_audit"][1]["blocked"] = True
    elif fault == "boolean_invocation":
        result["hook_audit"][1]["invocation_number"] = False
    elif fault == "wrong_step":
        result["hook_audit"][2]["step_index"] = 3
    elif fault == "wrong_args":
        result["hook_audit"][2]["args_sha256"] = "a" * 64
    elif fault == "allowed_pre":
        result["hook_audit"][2]["decision"] = "allow"
    elif fault == "post_present":
        result["hook_audit"].append({**result["hook_audit"][2], "event": "post"})
    else:
        result["stream_events"][-1]["step_state"] = "DONE"
    result_path.write_text(json.dumps(result))
    approval["result_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    outcome_path = root / "attempt-0004.result.json"
    outcome = json.loads(outcome_path.read_bytes())
    outcome["details"]["result_sha256"] = approval["result_sha256"]
    outcome_path.write_text(json.dumps(outcome))
    approval["outcome_sha256"] = hashlib.sha256(outcome_path.read_bytes()).hexdigest()
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="DENIAL_PROTOCOL_REPAIR_RESULT_NOT_ELIGIBLE"):
            budget.approve_denial_protocol_repair(approval)


@pytest.mark.parametrize("status", ["COMPLETED", "ABORTED"])
def test_denial_protocol_repair_does_not_reclassify_another_status(tmp_path, status):
    root, _, _, approval = denial_protocol_failed_state(tmp_path, outcome_status=status)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="DENIAL_PROTOCOL_REPAIR_OUTCOME_MISMATCH"):
            budget.approve_denial_protocol_repair(approval)


def test_denial_protocol_repair_never_recovers_fifth_failure_or_unfinished_attempt(tmp_path):
    root, _, _, approval = denial_protocol_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_denial_protocol_repair(approval)
        fifth = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        with pytest.raises(BudgetError, match="UNFINISHED_ATTEMPT"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        budget.finish(fifth, "FAILED", {"reason": "another failure"})
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        with pytest.raises(BudgetError, match="INVALID_DENIAL_PROTOCOL_REPAIR_APPROVAL"):
            budget.approve_denial_protocol_repair({**approval, "attempt_id": fifth})


def test_denial_protocol_repair_keeps_seven_and_twenty_two_caps(tmp_path):
    root, _, _, approval = denial_protocol_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_denial_protocol_repair(approval)
        for _ in range(3):
            attempt = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
            budget.finish(attempt, "COMPLETED")
        with pytest.raises(BudgetError, match="BUDGET_EXHAUSTED"):
            budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        for _ in range(22):
            attempt = budget.reserve("research", {"policy_hash": approval["policy_hash"]})
            budget.finish(attempt, "COMPLETED")
        with pytest.raises(BudgetError, match="BUDGET_EXHAUSTED"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        assert budget.snapshot()["reserved"] == {"diagnostic": 7, "research": 22}


@pytest.mark.parametrize(
    "fault",
    [
        "deleted",
        "changed",
        "pin_removed",
        "prior_changed",
        "diagnosis_changed",
        "snapshot_changed",
        "result_changed",
    ],
)
def test_denial_protocol_repair_chain_tamper_stops_reacquisition(tmp_path, fault):
    root, _, _, approval = denial_protocol_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_denial_protocol_repair(approval)
    if fault == "deleted":
        (root / "denial-protocol-repair-amendment.json").unlink()
    elif fault == "changed":
        (root / "denial-protocol-repair-amendment.json").write_text("{}")
    elif fault == "pin_removed":
        head = json.loads((root / "head.json").read_bytes())
        head.pop("denial_protocol_repair_sha256")
        (root / "head.json").write_text(json.dumps(head))
    elif fault == "prior_changed":
        (root / "plugin-startup-repair-amendment.json").write_text("{}")
    elif fault == "diagnosis_changed":
        Path(approval["diagnosis_path"]).write_text("{}")
    elif fault == "result_changed":
        Path(approval["result_path"]).write_text("{}")
    else:
        (tmp_path / "fourth-protocol" / "owned-protocol-snapshot.sqlite").write_bytes(b"changed")
    with pytest.raises(BudgetError, match="REPAIR"):
        PersistentBudget(root).acquire()
    assert not (root / "global-active.lock").exists()


def test_denial_protocol_repair_requires_owned_lock_and_immutable_decision(tmp_path):
    root, _, _, approval = denial_protocol_failed_state(tmp_path)
    with pytest.raises(BudgetError, match="LOCK_OWNERSHIP_UNVERIFIED"):
        PersistentBudget(root).approve_denial_protocol_repair(approval)
    with PersistentBudget(root) as budget:
        budget.approve_denial_protocol_repair(approval)
        raw = (root / "denial-protocol-repair-amendment.json").read_bytes()
        with pytest.raises(BudgetError, match="DENIAL_PROTOCOL_REPAIR_APPROVAL_CHANGED"):
            budget.approve_denial_protocol_repair({**approval, "policy_hash": "a" * 64})
        with pytest.raises(BudgetError, match="INVALID_DENIAL_PROTOCOL_REPAIR_APPROVAL"):
            budget.approve_denial_protocol_repair({**approval, "diagnostic_cap": 8})
        assert (root / "denial-protocol-repair-amendment.json").read_bytes() == raw


def plan_mode_failed_state(
    tmp_path, *, diagnosis_changes=None, result_changes=None, outcome_status="FAILED"
):
    root, original, _, previous = denial_protocol_failed_state(tmp_path)
    evidence = tmp_path / "fifth-plan-mode"
    evidence.mkdir()
    result_path = evidence / "result.json"
    result = json.loads(Path(previous["result_path"]).read_bytes())
    common = {
        "configuration_matches": True,
        "conversation_id": PLAN_MODE_REPAIR_CONVERSATION,
        "model_name": "gemini-4-argon-high",
        "nonce": "b" * 32,
        "workspaces": [str(tmp_path / "owned-fifth-workspace")],
        "invocation_number": None,
        "step_index": None,
        "tool_name": None,
        "args_sha256": hashlib.sha256(b"{}").hexdigest(),
    }
    audit = [
        {**common, "event": "session"},
        {**common, "event": "invocation", "invocation_number": 0, "blocked": False},
    ]
    audit.extend(
        {
            **common,
            "event": "pre",
            "decision": "deny",
            "tool_name": name,
            "step_index": index,
            "args_sha256": args_sha,
        }
        for name, index, args_sha in PLAN_MODE_DENIALS
    )
    audit.append({**common, "event": "postinvocation", "invocation_number": 0})
    for index in range(1, 5):
        audit.extend(
            [
                {**common, "event": "invocation", "invocation_number": index, "blocked": False},
                {**common, "event": "postinvocation", "invocation_number": index},
            ]
        )
    audit.append(
        {
            **common,
            "event": "stop",
            "fully_idle": True,
            "termination_reason": "MAX_FORCED_INVOCATIONS",
        }
    )
    prior_diagnosis = json.loads(Path(previous["diagnosis_path"]).read_bytes())
    completions = [
        {
            "tool_name": name,
            "step_index": index,
            "args_sha256": args_sha,
            "conversation_id": PLAN_MODE_REPAIR_CONVERSATION,
            "state": "ERROR",
            "error_message_sha256": hashlib.sha256(DENIAL_PROTOCOL_MESSAGE.encode()).hexdigest(),
            "error_message_characters": len(DENIAL_PROTOCOL_MESSAGE),
            "error_shape_valid": True,
            "exact_pre_tool_denial": True,
            "installed_binary_message_prefix": True,
            "output_empty": True,
            "output_type": "NoneType",
            "error_type": "TOOL_ERROR",
            "error_type_authority": "SHAPE_ONLY_NOT_PERMISSION_ENUM",
            "stream_denial_contract": "PINNED_CLI_ERROR_AND_TRUSTED_PRE_REQUIRED",
            "protocol_diagnosis_sha256": previous["diagnosis_sha256"],
            "protocol_snapshot_sha256": prior_diagnosis["source_snapshot_sha256"],
        }
        for name, index, args_sha in PLAN_MODE_DENIALS
    ]

    def step(kind):
        return {"event": "step_update", "step_state": "DONE", "step_type": kind, "tool_events": []}

    stream = [result["stream_events"][0], step("user_input"), step("agent_response")]
    stream.extend(
        {
            "event": "step_update",
            "step_state": state,
            "step_type": "tool",
            "tool_events": [{"state": state, "tool_name": name}],
        }
        for name, _, _ in PLAN_MODE_DENIALS
        for state in ("ACTIVE", "ERROR")
    )
    stream.append(step("agent_response"))
    for _ in range(3):
        stream.extend([step("user_input"), step("agent_response")])
    stream.append({"event": "result", "result_status": "SUCCESS"})
    result.update(
        {
            "policy_hash": previous["policy_hash"],
            "reason": "PROVIDER_OR_SCHEMA_FAILURE",
            "exit_code": 0,
            "hook_audit": audit,
            "stream_events": stream,
            "tool_completion_metadata": completions,
            **(result_changes or {}),
        }
    )
    result_path.write_text(json.dumps(result))
    result_sha = hashlib.sha256(result_path.read_bytes()).hexdigest()
    with PersistentBudget(root) as budget:
        budget.approve_denial_protocol_repair(previous)
        attempt = budget.reserve(
            "diagnostic",
            {
                "policy_hash": previous["policy_hash"],
                "stage": "filesystem_command_write_url_and_search",
            },
        )
        assert attempt == "attempt-0005"
        budget.finish(
            attempt,
            outcome_status,
            {
                "policy_hash": previous["policy_hash"],
                "reason": "PROVIDER_OR_SCHEMA_FAILURE",
                "result_path": str(result_path),
                "result_sha256": result_sha,
            },
        )
    snapshot = evidence / "owned-plan-mode-snapshot.sqlite"
    snapshot.write_bytes(b"Synthetic fifth snapshot: five generations and one executor")
    steps = [
        (0, 14, 3),
        (1, 15, 3),
        *[(i, 132, 7) for i in range(2, 7)],
        (7, 15, 3),
        (8, 14, 3),
        (9, 15, 3),
        (10, 14, 3),
        (11, 15, 3),
        (12, 14, 3),
        (13, 15, 3),
    ]
    diagnosis = {
        "version": "StockOSAGYPlanModeDiagnosisV1",
        "classification": "SYNTHETIC_PLAN_MODE_WITH_NO_ADMITTED_STRUCTURED_OBJECT",
        "conversation_id": PLAN_MODE_REPAIR_CONVERSATION,
        "owned_workspace_confirmed": True,
        "source_database": str(
            tmp_path / "conversations" / (PLAN_MODE_REPAIR_CONVERSATION + ".db")
        ),
        "source_read_mode": "ro_immutable_query_only_no_sidecars",
        "source_snapshot_path": str(snapshot),
        "source_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        "steps": [{"index": i, "type": t, "status": s} for i, t, s in steps],
        "gen_metadata_rows": 5,
        "executor_metadata_rows": 1,
        "synthetic_model_responses_present": True,
        "terminal_status": "SUCCESS",
        "terminal_exit_code": 0,
        "terminal_structured_object_admitted": False,
        "final_agent_response": '{"answer": "unavailable"}',
        "final_agent_response_payload_sha256": PLAN_MODE_RESPONSE_SHA256,
        "observed_denied_tool_names": ["read_url_content", "search_web", "view_file"],
        "observed_denied_count": 5,
        "command_write_subagent_coverage": "NOT_EXERCISED",
        "denial_message": DENIAL_PROTOCOL_MESSAGE,
        "all_attempted_tools_confirmed_pre_denied_with_empty_error_completion": True,
        "formal_database_writes": 0,
        "financial_documents_sent": 0,
        "settings_hooks_plugins_restored": True,
        "causality": "plan mode readonly behavior is documented; cause of missing structured object is not independently established",
        **(diagnosis_changes or {}),
    }
    diagnosis_path = evidence / "plan-mode-diagnosis.json"
    diagnosis_path.write_text(json.dumps(diagnosis))
    approval = {
        "version": "StockOSAGYPlanModeRepairApprovalV1",
        "decision": "APPROVED_BY_USER",
        "user_instruction": original["user_instruction"],
        "policy_hash": "b" * 64,
        "request_sha256": PINNED_REQUEST_SHA256,
        "research_binding": PINNED_RESEARCH_BINDING,
        "attempt_id": attempt,
        "reservation_sha256": hashlib.sha256((root / f"{attempt}.json").read_bytes()).hexdigest(),
        "outcome_sha256": hashlib.sha256(
            (root / f"{attempt}.result.json").read_bytes()
        ).hexdigest(),
        "result_path": str(result_path),
        "result_sha256": result_sha,
        "diagnosis_path": str(diagnosis_path),
        "diagnosis_sha256": hashlib.sha256(diagnosis_path.read_bytes()).hexdigest(),
        "prior_denial_protocol_repair_sha256": hashlib.sha256(
            (root / "denial-protocol-repair-amendment.json").read_bytes()
        ).hexdigest(),
    }
    return root, previous, approval


def test_plan_mode_repair_preserves_five_failed_runs_and_does_not_admit_raw_json(tmp_path):
    root, previous, approval = plan_mode_failed_state(tmp_path)
    protected = {p.name: p.read_bytes() for p in root.glob("*.json") if p.name != "head.json"}
    with PersistentBudget(root) as budget:
        amendment = budget.approve_plan_mode_repair(approval)
        assert budget.approve_plan_mode_repair(copy.deepcopy(approval)) == amendment
        snapshot = budget.snapshot()
        assert snapshot["remaining"] == {"diagnostic": 2, "research": 22}
        assert snapshot["reserved"] == {"diagnostic": 5, "research": 0}
        assert snapshot["active_policy_hash"] == approval["policy_hash"]
        assert snapshot["plan_mode_repair"]["attempt_id"] == "attempt-0005"
        with pytest.raises(BudgetError, match="RECOVERY_POLICY_MISMATCH"):
            budget.reserve("diagnostic", {"policy_hash": previous["policy_hash"]})
        sixth = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        assert sixth == "attempt-0006"
        budget.finish(sixth, "COMPLETED")
    with PersistentBudget(root) as budget:
        assert budget.snapshot()["active_policy_hash"] == approval["policy_hash"]
    assert {name: (root / name).read_bytes() for name in protected} == protected
    assert json.loads((root / "attempt-0005.result.json").read_bytes())["status"] == "FAILED"
    assert json.loads(Path(approval["result_path"]).read_bytes())["structured_output"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "generic-retry"),
        ("decision", "AUTO_APPROVED"),
        ("user_instruction", ""),
        ("user_instruction", "different instruction"),
        ("policy_hash", "c" * 64),
        ("policy_hash", "d" * 64),
        ("policy_hash", "e" * 64),
        ("policy_hash", "f" * 64),
        ("policy_hash", None),
        ("attempt_id", "attempt-0006"),
        ("request_sha256", "a" * 64),
        ("research_binding", "a" * 64),
        ("reservation_sha256", "a" * 64),
        ("outcome_sha256", "a" * 64),
        ("result_sha256", "a" * 64),
        ("diagnosis_sha256", "a" * 64),
        ("prior_denial_protocol_repair_sha256", "a" * 64),
        ("result_path", "relative.json"),
        ("diagnosis_path", "relative.json"),
    ],
)
def test_plan_mode_repair_requires_exact_approval_and_chain(tmp_path, field, value):
    root, previous, approval = plan_mode_failed_state(tmp_path)
    approval[field] = value
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="REPAIR"):
            budget.approve_plan_mode_repair(approval)
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            budget.reserve("research", {"policy_hash": previous["policy_hash"]})
    assert not (root / "plan-mode-repair-amendment.json").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"classification": "ARBITRARY_MODEL_FAILURE"},
        {"conversation_id": "unowned"},
        {"owned_workspace_confirmed": False},
        {"source_read_mode": "writable"},
        {"steps": []},
        {"gen_metadata_rows": 0},
        {"gen_metadata_rows": True},
        {"gen_metadata_rows": 6},
        {"executor_metadata_rows": 0},
        {"synthetic_model_responses_present": False},
        {"terminal_status": "ERROR"},
        {"terminal_exit_code": False},
        {"terminal_structured_object_admitted": True},
        {"final_agent_response": '{"answer":"bad"}'},
        {"final_agent_response_payload_sha256": "a" * 64},
        {"observed_denied_count": 6},
        {"observed_denied_tool_names": ["run_command"]},
        {"command_write_subagent_coverage": "PASS"},
        {"denial_message": "permission denied"},
        {"all_attempted_tools_confirmed_pre_denied_with_empty_error_completion": False},
        {"financial_documents_sent": 1},
        {"formal_database_writes": 1},
        {"settings_hooks_plugins_restored": False},
        {"causality": "definitely no inference"},
        {"source_snapshot_path": None},
        {"source_snapshot_sha256": "a" * 64},
    ],
)
def test_plan_mode_repair_is_not_generic_content_retry_or_qualification(tmp_path, changes):
    root, _, approval = plan_mode_failed_state(tmp_path, diagnosis_changes=changes)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="PLAN_MODE_REPAIR"):
            budget.approve_plan_mode_repair(approval)


@pytest.mark.parametrize(
    "changes",
    [
        {"structured_output": {"answer": "unavailable"}},
        {"reason": "QUALITY_REJECTED"},
        {"exit_code": -9},
        {"exit_code": False},
        {"permission_mode": "always-proceed"},
        {"owned_process_group_absent": False},
        {"financial_documents_sent": 1},
        {"formal_database_writes": 1},
        {"hook_audit": []},
        {"stream_events": []},
        {"tool_completion_metadata": []},
    ],
)
def test_plan_mode_repair_rejects_unbound_result_or_admitted_object(tmp_path, changes):
    root, _, approval = plan_mode_failed_state(tmp_path, result_changes=changes)
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="PLAN_MODE_REPAIR_RESULT_NOT_ELIGIBLE"):
            budget.approve_plan_mode_repair(approval)


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_nonce",
        "wrong_workspace",
        "wrong_conversation",
        "config_drift",
        "wrong_invocation",
        "blocked_invocation",
        "wrong_step",
        "wrong_args",
        "allow_pre",
        "missing_pre",
        "missing_postinvocation",
        "output_present",
        "different_error",
        "missing_exact_denial",
        "wrong_protocol_pin",
        "succeeded_tool",
        "unobserved_command",
        "stop_not_idle",
    ],
)
def test_plan_mode_repair_requires_all_five_exact_trusted_denials(tmp_path, fault):
    root, _, approval = plan_mode_failed_state(tmp_path)
    p = Path(approval["result_path"])
    result = json.loads(p.read_bytes())
    if fault == "wrong_nonce":
        result["hook_audit"][2]["nonce"] = "c" * 32
    elif fault == "wrong_workspace":
        result["hook_audit"][2]["workspaces"] = ["/unowned"]
    elif fault == "wrong_conversation":
        result["hook_audit"][2]["conversation_id"] = "unowned"
    elif fault == "config_drift":
        result["hook_audit"][2]["configuration_matches"] = False
    elif fault == "wrong_invocation":
        result["hook_audit"][1]["invocation_number"] = False
    elif fault == "blocked_invocation":
        result["hook_audit"][1]["blocked"] = True
    elif fault == "wrong_step":
        result["hook_audit"][2]["step_index"] = 3
    elif fault == "wrong_args":
        result["hook_audit"][2]["args_sha256"] = "a" * 64
    elif fault == "allow_pre":
        result["hook_audit"][2]["decision"] = "allow"
    elif fault == "missing_pre":
        result["hook_audit"].pop(2)
    elif fault == "missing_postinvocation":
        result["hook_audit"].pop(7)
    elif fault == "output_present":
        result["tool_completion_metadata"][0]["output_empty"] = False
    elif fault == "different_error":
        result["tool_completion_metadata"][0]["error_message_sha256"] = "a" * 64
    elif fault == "missing_exact_denial":
        result["tool_completion_metadata"][0]["exact_pre_tool_denial"] = False
    elif fault == "wrong_protocol_pin":
        result["tool_completion_metadata"][0]["protocol_diagnosis_sha256"] = "a" * 64
    elif fault == "succeeded_tool":
        result["stream_events"][4]["step_state"] = "DONE"
    elif fault == "unobserved_command":
        result["stream_events"][3]["tool_events"][0]["tool_name"] = "run_command"
    else:
        result["hook_audit"][-1]["fully_idle"] = False
    p.write_text(json.dumps(result))
    approval["result_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    outcome_path = root / "attempt-0005.result.json"
    outcome = json.loads(outcome_path.read_bytes())
    outcome["details"]["result_sha256"] = approval["result_sha256"]
    outcome_path.write_text(json.dumps(outcome))
    approval["outcome_sha256"] = hashlib.sha256(outcome_path.read_bytes()).hexdigest()
    with PersistentBudget(root) as budget:
        with pytest.raises(BudgetError, match="PLAN_MODE_REPAIR"):
            budget.approve_plan_mode_repair(approval)


def test_plan_mode_repair_never_skips_a_sixth_failure_or_unfinished_attempt(tmp_path):
    root, _, approval = plan_mode_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_plan_mode_repair(approval)
        sixth = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        with pytest.raises(BudgetError, match="UNFINISHED_ATTEMPT"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        budget.finish(sixth, "FAILED", {"reason": "any next failure"})
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        with pytest.raises(BudgetError, match="INVALID_PLAN_MODE_REPAIR_APPROVAL"):
            budget.approve_plan_mode_repair({**approval, "attempt_id": sixth})


def test_plan_mode_repair_keeps_original_caps_and_does_not_refund_five_failures(tmp_path):
    root, _, approval = plan_mode_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_plan_mode_repair(approval)
        for _ in range(2):
            attempt = budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
            budget.finish(attempt, "COMPLETED")
        with pytest.raises(BudgetError, match="BUDGET_EXHAUSTED"):
            budget.reserve("diagnostic", {"policy_hash": approval["policy_hash"]})
        for _ in range(22):
            attempt = budget.reserve("research", {"policy_hash": approval["policy_hash"]})
            budget.finish(attempt, "COMPLETED")
        with pytest.raises(BudgetError, match="BUDGET_EXHAUSTED"):
            budget.reserve("research", {"policy_hash": approval["policy_hash"]})
        assert budget.snapshot()["reserved"] == {"diagnostic": 7, "research": 22}


@pytest.mark.parametrize(
    "fault",
    [
        "deleted",
        "changed",
        "pin_removed",
        "prior_changed",
        "diagnosis_changed",
        "snapshot_changed",
        "result_changed",
    ],
)
def test_plan_mode_repair_tamper_fails_closed_on_reacquire(tmp_path, fault):
    root, _, approval = plan_mode_failed_state(tmp_path)
    with PersistentBudget(root) as budget:
        budget.approve_plan_mode_repair(approval)
    if fault == "deleted":
        (root / "plan-mode-repair-amendment.json").unlink()
    elif fault == "changed":
        (root / "plan-mode-repair-amendment.json").write_text("{}")
    elif fault == "pin_removed":
        head = json.loads((root / "head.json").read_bytes())
        head.pop("plan_mode_repair_sha256")
        (root / "head.json").write_text(json.dumps(head))
    elif fault == "prior_changed":
        (root / "denial-protocol-repair-amendment.json").write_text("{}")
    elif fault == "diagnosis_changed":
        Path(approval["diagnosis_path"]).write_text("{}")
    elif fault == "result_changed":
        Path(approval["result_path"]).write_text("{}")
    else:
        (tmp_path / "fifth-plan-mode" / "owned-plan-mode-snapshot.sqlite").write_bytes(b"changed")
    with pytest.raises(BudgetError, match="REPAIR"):
        PersistentBudget(root).acquire()
    assert not (root / "global-active.lock").exists()


def test_plan_mode_repair_requires_owned_lock_and_immutable_approval(tmp_path):
    root, _, approval = plan_mode_failed_state(tmp_path)
    with pytest.raises(BudgetError, match="LOCK_OWNERSHIP_UNVERIFIED"):
        PersistentBudget(root).approve_plan_mode_repair(approval)
    with PersistentBudget(root) as budget:
        budget.approve_plan_mode_repair(approval)
        raw = (root / "plan-mode-repair-amendment.json").read_bytes()
        with pytest.raises(BudgetError, match="PLAN_MODE_REPAIR_APPROVAL_CHANGED"):
            budget.approve_plan_mode_repair({**approval, "policy_hash": "a" * 64})
        with pytest.raises(BudgetError, match="INVALID_PLAN_MODE_REPAIR_APPROVAL"):
            budget.approve_plan_mode_repair({**approval, "diagnostic_cap": 8})
        assert (root / "plan-mode-repair-amendment.json").read_bytes() == raw
