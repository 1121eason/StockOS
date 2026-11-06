"""Frozen synthetic native rows and immutable recovery; no live AGY is invoked."""

import copy
import json

import pytest

from valuation_engine.ai.agy_explanation import BudgetError, PersistentBudget
from valuation_engine.ai.agy_guarded import (
    AGENT,
    CLI_SHA,
    DENIED_CHILD,
    MODEL,
    PRE_TOOL_DENIAL_REASON,
    file_sha,
    save,
)
from valuation_engine.ai.agy_permission_evidence import (
    PermissionCompletionBudget,
    validate_permission_evidence,
)


def field(number, text):
    raw = text.encode()
    size, length = len(raw), bytearray()
    while size >= 128:
        length.append((size & 127) | 128)
        size >>= 7
    length.append(size)
    return bytes([number << 3 | 2]) + bytes(length) + raw


@pytest.fixture
def evidence(tmp_path):
    result_path = tmp_path / "run/attempt-0001/result.json"
    result_path.parent.mkdir(parents=True)
    targets = result_path.parent.parent / "native-canaries/synthetic-repository"
    cid = "synthetic-owned-conversation"
    message = "tool call denied by pre-tool hook: " + PRE_TOOL_DENIAL_REASON
    args = [
        {
            "CommandLine": "/usr/bin/touch " + str(targets / "command-marker"),
            "BypassSandbox": False,
        },
        {"Path": str(targets / "write-marker"), "Content": "synthetic"},
        {"TypeName": DENIED_CHILD, "Prompt": "say synthetic", "Role": "synthetic test"},
    ]
    rows, audit = (
        [],
        [
            {
                "event": "invocation",
                "blocked": False,
                "conversation_id": cid,
                "configuration_matches": True,
            }
        ],
    )
    for index, (name, values) in enumerate(
        zip(("run_command", "write_file", "invoke_subagent"), args, strict=True), 2
    ):
        rows.append(
            {
                "index": index,
                "type": 132,
                "status": 7,
                "has_subtrajectory": 0,
                "tool_name": name,
                "step_payload_hex": (
                    field(1, name) + field(2, json.dumps(values)) + field(3, cid)
                ).hex(),
                "error_details_hex": (field(2, message) + field(3, message)).hex(),
            }
        )
        audit.append(
            {
                "event": "pre",
                "decision": "deny",
                "conversation_id": cid,
                "configuration_matches": True,
                "step_index": index,
                "tool_name": name,
                "args_sha256": "a" * 64,
            }
        )
    snapshot = {
        "version": "StockOSAGYNativeDenialRowsV1",
        "cli_sha256": CLI_SHA,
        "conversation_id": cid,
        "source_read_mode": "ro_query_only",
        "owned_workspace_confirmed": True,
        "steps": rows,
    }
    result = {
        "status": "FAIL",
        "exit_code": -9,
        "financial_documents_sent": 0,
        "formal_database_writes": 0,
        "permission_mode": "strict",
        "actual_model": MODEL,
        "requested_agent": "CLI_DEFAULT",
        "owned_process_group_absent": True,
        "reason": "STREAM_CONTRACT_UNVERIFIED",
        "hook_audit": audit,
    }
    save(result_path, result)
    snapshot["original_result_sha256"] = file_sha(result_path)
    snapshot_path = result_path.parent.parent / "native-denial-rows.json"
    save(snapshot_path, snapshot)
    return snapshot, result, result_path, snapshot_path


def test_native_scope_is_verified_without_claiming_stream_or_model_answer_passed(evidence):
    snapshot, result, path, _ = evidence
    observations = validate_permission_evidence(snapshot, result, path)
    assert {r["tool_name"] for r in observations} == {
        "run_command",
        "write_file",
        "invoke_subagent",
    }
    assert result["status"] == "FAIL"
    assert all(r["pre_args_sha256"] == "a" * 64 for r in observations)
    assert all(r["native_args_sha256"] != "a" * 64 for r in observations)


@pytest.mark.parametrize(
    "mutation",
    [
        "output",
        "child",
        "wrong_error",
        "other_tool",
        "other_conversation",
        "pre_allowed",
        "duplicate_pre",
        "wrong_command",
        "wrong_write",
        "other_child",
        "no_ownership",
        "other_binary",
        "other_model",
        "mode",
        "financial_data",
        "bool_zero",
        "config_drift",
        "missing_operation",
        "foreign_row",
    ],
)
def test_incomplete_foreign_or_successful_operations_cannot_be_revalidated(evidence, mutation):
    snapshot, result, path, _ = evidence
    s, r = copy.deepcopy(snapshot), copy.deepcopy(result)
    if mutation == "output":
        s["steps"][0]["status"] = 3
    elif mutation == "child":
        s["steps"][2]["has_subtrajectory"] = 1
    elif mutation == "wrong_error":
        s["steps"][0]["error_details_hex"] = field(2, "ordinary failure").hex()
    elif mutation == "other_tool":
        r["hook_audit"][1]["tool_name"] = "different"
    elif mutation == "other_conversation":
        r["hook_audit"][1]["conversation_id"] = "foreign"
    elif mutation == "pre_allowed":
        r["hook_audit"][1]["decision"] = "allow"
    elif mutation == "duplicate_pre":
        r["hook_audit"].append(copy.deepcopy(r["hook_audit"][1]))
    elif mutation == "wrong_command":
        s["steps"][0]["step_payload_hex"] = (
            field(1, "run_command")
            + field(2, json.dumps({"CommandLine": "echo other", "BypassSandbox": False}))
            + field(3, s["conversation_id"])
        ).hex()
    elif mutation == "wrong_write":
        s["steps"][1]["step_payload_hex"] = (
            field(1, "write_file")
            + field(2, json.dumps({"Path": "other", "Content": "synthetic"}))
            + field(3, s["conversation_id"])
        ).hex()
    elif mutation == "other_child":
        s["steps"][2]["step_payload_hex"] = (
            field(1, "invoke_subagent")
            + field(2, json.dumps({"TypeName": "other", "Prompt": "synthetic"}))
            + field(3, s["conversation_id"])
        ).hex()
    elif mutation == "no_ownership":
        s["owned_workspace_confirmed"] = False
    elif mutation == "other_binary":
        s["cli_sha256"] = "b" * 64
    elif mutation == "other_model":
        r["actual_model"] = "other"
    elif mutation == "mode":
        r["permission_mode"] = "always-proceed"
    elif mutation == "financial_data":
        r["financial_documents_sent"] = 1
    elif mutation == "bool_zero":
        r["financial_documents_sent"] = False
    elif mutation == "config_drift":
        r["hook_audit"][0]["configuration_matches"] = False
    elif mutation == "missing_operation":
        s["steps"].pop()
    elif mutation == "foreign_row":
        s["steps"][0]["step_payload_hex"] = (
            field(1, "run_command") + field(2, "{}") + field(3, "foreign")
        ).hex()
    with pytest.raises(ValueError):
        validate_permission_evidence(s, r, path)


def test_marker_existence_contradicts_denial(evidence):
    s, r, p, _ = evidence
    marker = p.parent.parent / "native-canaries/synthetic-repository/write-marker"
    marker.parent.mkdir(parents=True)
    marker.write_text("contradiction")
    with pytest.raises(ValueError, match="MARKER_EXISTS"):
        validate_permission_evidence(s, r, p)


@pytest.mark.parametrize("next_failure", ["diagnostic", "research"])
def test_fixed_revalidation_preserves_failed_bytes_caps_and_blocks_later_failure(
    tmp_path, evidence, next_failure
):
    s, r, result_path, snapshot_path = evidence
    root = tmp_path / "budget"
    with PersistentBudget(root, diagnostic_cap=4) as b:
        attempt = b.reserve("diagnostic", metadata={"policy_hash": "old"})
        b.finish(
            attempt,
            "FAILED",
            details={"result_path": str(result_path), "result_sha256": file_sha(result_path)},
        )
    before = {p.name: p.read_bytes() for p in root.glob("attempt-*.json")}
    save(
        root / "authorization.json",
        {
            "user_instruction": "new task",
            "new_allocation_caps": {"diagnostic": 4, "research": 22},
            "request_binding": {"request_sha256": "request", "research_binding": "binding"},
        },
    )
    approval = {
        "attempt_id": "attempt-0001",
        "policy_hash": "new",
        "user_instruction": "new task",
        "request_sha256": "request",
        "research_binding": "binding",
        "reservation_sha256": file_sha(root / "attempt-0001.json"),
        "outcome_sha256": file_sha(root / "attempt-0001.result.json"),
        "result_path": str(result_path),
        "result_sha256": file_sha(result_path),
        "snapshot_path": str(snapshot_path),
        "snapshot_sha256": file_sha(snapshot_path),
    }
    revalidation = {
        "version": "StockOSAGYPermissionRevalidationV1",
        "decision": "ENGINEERING_REVALIDATION_WITHIN_CURRENT_OWNER_AUTHORIZATION",
        "approval": approval,
    }
    save(root / "permission-revalidation.json", revalidation)
    with PermissionCompletionBudget(root, revalidation=revalidation, diagnostic_cap=4) as b:
        with pytest.raises(BudgetError, match="POLICY_MISMATCH"):
            b.reserve("diagnostic", metadata={"policy_hash": "old"})
        second = b.reserve("diagnostic", metadata={"policy_hash": "new"})
        b.finish(second, "COMPLETED")
        failed = b.reserve(next_failure, metadata={"policy_hash": "new"})
        b.finish(failed, "FAILED")
        with pytest.raises(BudgetError, match="PRIOR_ATTEMPT_FAILED"):
            b.reserve("research", metadata={"policy_hash": "new"})
        assert b.snapshot()["reserved"]["diagnostic"] >= 2
    assert all((root / name).read_bytes() == raw for name, raw in before.items())


def readonly_copy(evidence):
    s, r, p, _ = copy.deepcopy(evidence)
    p = p.parent.parent / "attempt-0002/result.json"
    p.parent.mkdir(parents=True)
    s.update(version="StockOSAGYNativeReadonlyDenialRowsV1", readonly_canary_path="/synthetic/canary")
    r.update(exit_code=0, reason="RESULT_INVALID_JSON", requested_agent=AGENT, actual_agent=AGENT)
    names = ("view_file", "read_url_content", "search_web")
    args = ({"AbsolutePath": "/synthetic/canary"}, {"Url": "https://example.com/"},
            {"query": "StockOS synthetic permissions canary"})
    for row, pre, name, value in zip(s["steps"], r["hook_audit"][1:], names, args, strict=True):
        row["tool_name"] = pre["tool_name"] = name
        row["step_payload_hex"] = (field(1, name) + field(2, json.dumps(value))
                                   + field(3, s["conversation_id"])
                                   + bytes.fromhex("2203010001")).hex()
    save(p, r)
    s["original_result_sha256"] = file_sha(p)
    snapshot = p.parent.parent / "native-readonly-denial-rows.json"
    save(snapshot, s)
    return s, r, p, snapshot


@pytest.mark.parametrize("wrong", [None, "view_file", "read_url_content", "search_web", "actor"])
def test_readonly_native_denials_require_exact_targets_and_actor(evidence, wrong):
    s, r, p, _ = readonly_copy(evidence)
    if wrong == "actor":
        r["actual_agent"] = "other"
    elif wrong:
        row = next(row for row in s["steps"] if row["tool_name"] == wrong)
        row["step_payload_hex"] = (field(1, wrong) + field(2, '{"wrong":"target"}')
                                   + field(3, s["conversation_id"])).hex()
    if wrong:
        with pytest.raises(ValueError):
            validate_permission_evidence(s, r, p, readonly=True)
    else:
        assert len(validate_permission_evidence(s, r, p, readonly=True)) == 3


def test_two_failed_diagnostics_can_be_independently_reviewed_without_refunds(tmp_path, evidence):
    second = readonly_copy(evidence)
    root = tmp_path / "review-v2-budget"
    # Build the second historical FAILED row using the first immutable review.
    with PersistentBudget(root, diagnostic_cap=4) as b:
        first = b.reserve("diagnostic", metadata={"policy_hash": "old"})
        b.finish(first, "FAILED", details={"result_path": str(evidence[2]),
                                           "result_sha256": file_sha(evidence[2])})
    def approval(index, proof):
        return {"attempt_id": f"attempt-{index:04d}", "policy_hash": "new",
                "user_instruction": "task", "request_sha256": "req", "research_binding": "bind",
                "reservation_sha256": file_sha(root / f"attempt-{index:04d}.json"),
                "outcome_sha256": file_sha(root / f"attempt-{index:04d}.result.json"),
                "result_path": str(proof[2]), "result_sha256": file_sha(proof[2]),
                "snapshot_path": str(proof[3]), "snapshot_sha256": file_sha(proof[3])}
    save(root / "authorization.json", {"user_instruction": "task",
         "new_allocation_caps": {"diagnostic": 4, "research": 22},
         "request_binding": {"request_sha256": "req", "research_binding": "bind"}})
    review = {"version": "StockOSAGYPermissionRevalidationV1",
              "decision": "ENGINEERING_REVALIDATION_WITHIN_CURRENT_OWNER_AUTHORIZATION",
              "approval": approval(1, evidence)}
    save(root / "permission-revalidation.json", review)
    with PermissionCompletionBudget(root, revalidation=review, diagnostic_cap=4) as b:
        attempt = b.reserve("diagnostic", metadata={"policy_hash": "new"})
        b.finish(attempt, "FAILED", details={"result_path": str(second[2]),
                                           "result_sha256": file_sha(second[2])})
    originals = {p.name: p.read_bytes() for p in root.glob("attempt-*.json")}
    review2 = {**review, "version": "StockOSAGYPermissionRevalidationV2",
               "additional_reviews": [approval(2, second)]}
    save(root / "permission-revalidation-v2.json", review2)
    with PermissionCompletionBudget(root, revalidation=review2,
                                   record_name="permission-revalidation-v2.json", diagnostic_cap=4) as b:
        for _ in range(2):
            b.finish(b.reserve("diagnostic", metadata={"policy_hash": "new"}), "COMPLETED")
        with pytest.raises(BudgetError, match="EXHAUSTED"):
            b.reserve("diagnostic", metadata={"policy_hash": "new"})
        assert b.snapshot()["reserved"] == {"diagnostic": 4, "research": 0}
        assert b.snapshot()["diagnostic_revalidated_attempts"] == ["attempt-0001", "attempt-0002"]
    assert all((root / name).read_bytes() == raw for name, raw in originals.items())
