"""Pure boundaries and standalone hook fixtures; no AGY or provider is invoked."""

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from valuation_engine.ai import agy_guarded
from valuation_engine.ai.agy_guarded import (
    AGENT,
    DENIED_CHILD,
    DIAGNOSTIC_TOOLS,
    MODEL,
    PRE_TOOL_DENIAL_MESSAGES,
    PRE_TOOL_DENIAL_REASON,
    GuardedTransport,
    definition,
    encoded,
    kernel_profile,
    read_audit,
    sha,
    summarize_result,
    summarize_tool_completion,
    tool_name,
    tool_nodes,
    validate_step,
    verify_boundary,
)

HOOK_SOURCE = Path(__file__).resolve().parents[2] / "scripts/agy_evidence_hook.py"
NONCE = "synthetic-owned-hook-nonce"


def audit_row(cwd, event, **extra):
    return {
        "event": event,
        "nonce": NONCE,
        "configuration_matches": True,
        "conversation_id": "synthetic-conversation",
        "workspaces": [str(cwd)],
        "model_name": MODEL,
        **({"args_sha256": "a" * 64} if event in ("pre", "post") else {}),
        **extra,
    }


def baseline(cwd):
    return [
        audit_row(cwd, "session"),
        audit_row(cwd, "invocation", blocked=False, invocation_number=0),
    ]


def denied_diagnostic(cwd, name="view_file"):
    return [
        *baseline(cwd),
        audit_row(cwd, "pre", tool_name=name, decision="deny", step_index=2),
        audit_row(
            cwd,
            "post",
            tool_name=name,
            error_present=True,
            denial_observed=True,
            step_index=2,
        ),
    ]


def test_pristine_research_boundary_does_not_require_a_tool_attempt(tmp_path):
    audit = baseline(tmp_path)
    before = copy.deepcopy(audit)
    assert verify_boundary(audit, NONCE, tmp_path, [], diagnostic=False) == []
    assert audit == before


@pytest.mark.parametrize("event", ["session", "invocation"])
def test_both_session_and_pre_model_invocation_evidence_are_required(tmp_path, event):
    audit = [row for row in baseline(tmp_path) if row["event"] != event]
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, [], diagnostic=False)


@pytest.mark.parametrize(
    "field,value",
    [
        ("nonce", "foreign-hook"),
        ("nonce", None),
        ("configuration_matches", False),
        ("configuration_matches", None),
        ("configuration_matches", 1),
        ("conversation_id", None),
        ("workspaces", []),
        ("workspaces", "/not-a-workspace-list"),
    ],
)
def test_untrusted_or_mismatched_hook_context_cannot_pass(tmp_path, field, value):
    audit = baseline(tmp_path)
    audit[1][field] = value
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, [], diagnostic=True)


def test_conversation_and_workspace_must_belong_to_this_one_call(tmp_path):
    audit = baseline(tmp_path)
    audit[1]["conversation_id"] = "another-conversation"
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, [], diagnostic=True)
    audit = baseline(tmp_path)
    audit[1]["workspaces"] = [str(tmp_path / "outside")]
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, [], diagnostic=True)


def test_empty_conversation_identifier_cannot_be_used_as_identity(tmp_path):
    audit = baseline(tmp_path)
    for row in audit:
        row["conversation_id"] = ""
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, [], diagnostic=False)


@pytest.mark.parametrize("number", [None, True, "0", -1])
def test_unknown_or_invalid_model_invocation_counters_cannot_pass(tmp_path, number):
    audit = baseline(tmp_path)
    audit[1]["invocation_number"] = number
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, [], diagnostic=True)


def test_any_blocked_invocation_invalidates_the_whole_stage(tmp_path):
    audit = [
        *baseline(tmp_path),
        audit_row(tmp_path, "invocation", blocked=True, invocation_number=1),
    ]
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, [], diagnostic=True)


def test_research_rejects_even_a_successfully_denied_external_attempt(tmp_path):
    audit = denied_diagnostic(tmp_path)
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, ["view_file"], diagnostic=False)
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, [], diagnostic=False)


def test_diagnostic_requires_trusted_deny_and_matching_denial_completion(tmp_path):
    assert verify_boundary(
        denied_diagnostic(tmp_path), NONCE, tmp_path, ["view_file"], diagnostic=True
    ) == ["view_file"]


@pytest.mark.parametrize(
    "fault",
    ["allow", "missing_pre", "different_tool", "missing_post", "success_post", "unknown_post"],
)
def test_successful_or_unaccounted_diagnostic_tools_never_pass(tmp_path, fault):
    audit = denied_diagnostic(tmp_path)
    if fault == "allow":
        audit[2]["decision"] = "allow"
    elif fault == "missing_pre":
        audit.pop(2)
    elif fault == "different_tool":
        audit[2]["tool_name"] = "run_command"
    elif fault == "missing_post":
        audit.pop()
    elif fault == "success_post":
        audit[-1].update(error_present=False, denial_observed=False)
    else:
        audit[-1].update(error_present=None, denial_observed=None)
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, ["view_file"], diagnostic=True)


@pytest.mark.parametrize(
    "fault", ["two_pre_one_post", "two_post_one_pre", "different_args", "different_step"]
)
def test_each_external_attempt_needs_its_own_matching_deny_completion(tmp_path, fault):
    audit = denied_diagnostic(tmp_path)
    if fault == "two_pre_one_post":
        audit.insert(3, copy.deepcopy(audit[2]))
    elif fault == "two_post_one_pre":
        audit.append(copy.deepcopy(audit[-1]))
    elif fault == "different_args":
        audit[-1]["args_sha256"] = "b" * 64
    else:
        audit[-1]["step_index"] = 3
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, ["view_file"], diagnostic=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("step_index", None),
        ("step_index", True),
        ("step_index", -1),
        ("step_index", "2"),
        ("args_sha256", None),
        ("args_sha256", "a" * 63),
        ("args_sha256", "not-a-hash"),
    ],
)
def test_external_deny_identity_cannot_be_unknown_or_invalid(tmp_path, field, value):
    audit = denied_diagnostic(tmp_path)
    audit[2][field] = value
    with pytest.raises(ValueError):
        verify_boundary(audit, NONCE, tmp_path, ["view_file"], diagnostic=True)


def test_kernel_profile_protects_formal_repository_and_real_settings(tmp_path):
    formal = tmp_path / "formal StockOS"
    settings = tmp_path / "AGY settings.json"
    profile = kernel_profile([formal], [settings])
    assert profile.startswith("(version 1)\n(allow default)\n")
    assert f"(deny file-read* file-write* (subpath {json.dumps(str(formal))}))" in profile
    assert f"(deny file-write* (literal {json.dumps(str(settings))}))" in profile
    assert profile.count("(deny ") == 2


def test_diagnostic_and_research_agents_have_distinct_explicit_capabilities():
    diagnostic = definition(True)
    research = definition(False)
    for text in (diagnostic, research):
        assert "name: " + AGENT in text
        assert "subagent: false" in text
        assert "mcpServers: []" in text
        assert "skills: []" in text
        assert "plugins: []" in text
        assert "dangerously-skip-permissions" not in text
        assert "always-proceed" not in text
    research_tools = json.loads(
        next(line[7:] for line in research.splitlines() if line.startswith("tools: "))
    )
    assert not any(line.startswith("tools:") for line in diagnostic.splitlines())
    assert "view_file" in DIAGNOSTIC_TOOLS and "run_command" in DIAGNOSTIC_TOOLS
    assert research_tools == ["finish"]
    assert "commandExecutionPolicy: sandbox" in diagnostic
    assert "commandExecutionPolicy: off" in research


@pytest.mark.parametrize("value", [None, "RAW_OUTPUT_MARKER", {}, [], 0, False])
def test_terminal_result_metadata_reports_shape_without_output_values(value):
    result = {"status": "SUCCESS", "structured_output": value, "response": "RAW_RESPONSE_MARKER"}
    metadata = summarize_result(result)
    assert metadata["result_fields"] == ["response", "status", "structured_output"]
    assert metadata["has_structured_output"] is True
    assert metadata["structured_output_type"] == type(value).__name__
    assert "RAW_OUTPUT_MARKER" not in json.dumps(metadata)
    assert "RAW_RESPONSE_MARKER" not in json.dumps(metadata)


def test_terminal_result_metadata_distinguishes_absent_key_from_explicit_null():
    metadata = summarize_result({"status": "SUCCESS"})
    assert metadata["has_structured_output"] is False
    assert metadata["structured_output_type"] == "NoneType"
    assert metadata["result_fields"] == ["status"]
    with pytest.raises(ValueError, match="INVALID_RESULT"):
        summarize_result(None)


@pytest.mark.parametrize("diagnostic", [False, True])
def test_launch_preparation_uses_accept_edits_and_protects_every_agent(
    tmp_path, monkeypatch, diagnostic
):
    hook = tmp_path / "synthetic-hook-source.py"
    hook.write_text("# synthetic offline hook fixture\n")
    cwd = tmp_path / "owned-workspace"
    cwd.mkdir()
    monkeypatch.setattr(agy_guarded, "HOOK", hook)
    monkeypatch.setattr(agy_guarded, "subscription_environment", lambda: {})
    observed = {}

    class LaunchIntercepted(Exception):
        pass

    def intercept(argv, **kwargs):
        observed["argv"] = argv
        observed["cwd"] = kwargs["cwd"]
        raise LaunchIntercepted

    monkeypatch.setattr(agy_guarded.subprocess, "Popen", intercept)
    transport = GuardedTransport(
        output=tmp_path, budget=None, policy_hash="synthetic", protected_hashes={}, denied_roots=[]
    )
    with pytest.raises(LaunchIntercepted):
        transport._call(
            cwd,
            {"task": "synthetic", "untrusted_data": {}, "response_schema": {"type": "object"}},
            diagnostic=diagnostic,
            timeout=1,
        )
    argv = observed["argv"]
    assert argv[argv.index("--mode") + 1] == "accept-edits"
    assert "--sandbox" in argv
    assert observed["cwd"] == cwd
    guard = json.loads((cwd / "guard.json").read_text())
    primary = cwd / ".agents/agents" / AGENT / "agent.md"
    child = cwd / ".agents/agents" / DENIED_CHILD / "agent.md"
    agents = [primary, child] if diagnostic else [primary]
    for agent in agents:
        assert guard["protected_hashes"][str(agent)] == sha(agent.read_bytes())
        assert agent.stat().st_mode & 0o777 == 0o400
        assert f"(literal {json.dumps(str(agent))})" in (cwd / "profile.sb").read_text()
    if diagnostic:
        text = child.read_text()
        for field in (
            "mainAgent: false",
            "subagent: true",
            "tools: []",
            "commandExecutionPolicy: off",
            "mcpServers: []",
            "plugins: []",
        ):
            assert field in text
        assert not any(line.startswith("tools:") for line in primary.read_text().splitlines())
    else:
        assert not child.exists()
        assert 'tools: ["finish"]' in primary.read_text()


@pytest.mark.parametrize(
    "diagnostic,forbid,denied,outcome",
    [
        (True, True, ["view_file"], "FAILED"),
        (True, True, [], "COMPLETED"),
        (True, False, ["view_file"], "COMPLETED"),
        (False, True, ["view_file"], "FAILED"),
    ],
)
def test_external_attempt_guard_precedes_validation_and_budget_completion(
    tmp_path, monkeypatch, diagnostic, forbid, denied, outcome
):
    cli = tmp_path / "synthetic-cli"
    cli.write_bytes(b"not executable; never launched")
    monkeypatch.setattr(agy_guarded, "CLI", cli)
    monkeypatch.setattr(agy_guarded, "CLI_SHA", sha(cli.read_bytes()))

    class Budget:
        def __init__(self):
            self.finished = []

        def reserve(self, phase, **kwargs):
            return "synthetic-attempt"

        def finish(self, attempt, state, **kwargs):
            self.finished.append(state)

    budget = Budget()
    transport = GuardedTransport(
        output=tmp_path,
        budget=budget,
        policy_hash="synthetic",
        protected_hashes={},
        denied_roots=[],
        qualification={"status": "PASS_CONTROLLED_BOUNDARY", "policy_hash": "synthetic"},
    )
    monkeypatch.setattr(
        transport,
        "_call",
        lambda *args, **kwargs: {
            "status": "PASS",
            "reason": None,
            "denied_tools": denied,
            "structured_output": {"answer": "unavailable"},
        },
    )
    validations = []

    def validate(value):
        validations.append(value)
        return value

    if outcome == "FAILED":
        with pytest.raises(ValueError, match="EXTERNAL_TOOL_ATTEMPT_FORBIDDEN"):
            transport.request(
                "synthetic",
                {},
                diagnostic=diagnostic,
                validate=validate,
                forbid_external_tools=forbid,
            )
        assert validations == []
        failure = json.loads((tmp_path / "synthetic-attempt/result.json").read_text())
        assert failure["structured_output"] is None
        assert not (tmp_path / "synthetic-attempt/admitted.json").exists()
    else:
        output, _ = transport.request(
            "synthetic", {}, diagnostic=diagnostic, validate=validate, forbid_external_tools=forbid
        )
        assert output == {"answer": "unavailable"}
        assert len(validations) == 1
    assert budget.finished == [outcome]


def terminal_tool_completion(**overrides):
    return {
        "conversation_id": "synthetic-conversation",
        "step_index": 2,
        "state": "DONE",
        "step_type": "tool",
        "tool_name": "view_file",
        "tool_info": {
            "name": "view_file",
            "parameters": {},
            "error": {
                "type": "unverified_type",
                "message": "Tool call denied by pre-tool hook: synthetic deny reason",
            },
        },
        **overrides,
    }


def completion_audit(cwd):
    audit = denied_diagnostic(cwd)
    for row in audit:
        if row["event"] in ("pre", "post"):
            row["args_sha256"] = sha(encoded({}))
    return audit


def test_stream_metadata_is_safe_and_never_claims_unverified_permission_type():
    step = terminal_tool_completion()
    step["tool_info"]["parameters"] = {"secret": "RAW_PARAMETER_MARKER"}
    step["tool_info"]["error"]["message"] += " RAW_ERROR_MARKER"
    before = copy.deepcopy(step)
    metadata = summarize_tool_completion(step)
    assert metadata["stream_denial_contract"] == "POST_HOOK_PROOF_REQUIRED"
    assert metadata["installed_binary_message_prefix"] is True
    assert metadata["error_type"] == "unverified_type"
    assert metadata["args_sha256"] == sha(encoded(step["tool_info"]["parameters"]))
    assert "RAW_PARAMETER_MARKER" not in json.dumps(metadata)
    assert "RAW_ERROR_MARKER" not in json.dumps(metadata)
    assert step == before


def test_done_step_cannot_replace_missing_post_without_pinned_error_state(tmp_path):
    audit = completion_audit(tmp_path)
    audit.pop()
    with pytest.raises(ValueError, match="COMPLETION_UNVERIFIED"):
        verify_boundary(
            audit,
            NONCE,
            tmp_path,
            ["view_file"],
            diagnostic=True,
            stream_completions=[terminal_tool_completion()],
        )


def test_existing_trusted_post_path_kept_with_consistent_non_success_stream(tmp_path):
    assert verify_boundary(
        completion_audit(tmp_path),
        NONCE,
        tmp_path,
        ["view_file"],
        diagnostic=True,
        stream_completions=[terminal_tool_completion()],
    ) == ["view_file"]


def pinned_error_completion(**overrides):
    step = terminal_tool_completion(state="ERROR", **overrides)
    step["tool_info"]["error"] = {
        "type": "opaque_cli_error_type",
        "message": next(iter(PRE_TOOL_DENIAL_MESSAGES)),
    }
    return step


@pytest.mark.parametrize("message", sorted(PRE_TOOL_DENIAL_MESSAGES))
@pytest.mark.parametrize("error_type", ["opaque_cli_error_type", "permission_denied", "USER_ERROR"])
def test_exact_owned_hook_error_state_completes_pre_deny_without_post(
    tmp_path, message, error_type
):
    audit = completion_audit(tmp_path)
    audit.pop()
    step = pinned_error_completion()
    step["tool_info"]["error"] = {"type": error_type, "message": message}
    before = copy.deepcopy((audit, step))
    assert verify_boundary(
        audit, NONCE, tmp_path, ["view_file"], diagnostic=True, stream_completions=[step]
    ) == ["view_file"]
    metadata = summarize_tool_completion(step)
    assert metadata["exact_pre_tool_denial"] is True
    assert metadata["error_type_authority"] == "SHAPE_ONLY_NOT_PERMISSION_ENUM"
    assert metadata["stream_denial_contract"] == "PINNED_CLI_ERROR_AND_TRUSTED_PRE_REQUIRED"
    assert (
        metadata["protocol_snapshot_sha256"]
        == "f58f790ff6c0132e21ca8a2bd6a82f2b368d960d8e6525d76f63accb1dc69f71"
    )
    assert (audit, step) == before


@pytest.mark.parametrize("kind", ["user_input", "agent_response", "checkpoint"])
def test_error_state_is_not_granted_to_non_tool_steps(kind):
    with pytest.raises(ValueError, match="STREAM_CONTRACT_UNVERIFIED"):
        validate_step(
            {
                "conversation_id": "synthetic-conversation",
                "step_index": 2,
                "step_type": kind,
                "state": "ERROR",
            }
        )


@pytest.mark.parametrize(
    "message",
    [
        "permission denied",
        "permission subsystem unavailable",
        "not denied",
        "tool call denied by pre-tool hook: different hook reason",
        "tool call denied by pre-tool hook: ",
        "tool call denied by pre-tool hook: " + PRE_TOOL_DENIAL_REASON + " extra data",
        "tool call denied by pre-tool hook: " + PRE_TOOL_DENIAL_REASON + "\n",
        "tool call was not denied by pre-tool hook: " + PRE_TOOL_DENIAL_REASON,
    ],
)
def test_unknown_message_cannot_mask_error_even_when_post_claims_denial(tmp_path, message):
    step = pinned_error_completion()
    step["tool_info"]["error"]["message"] = message
    with pytest.raises(ValueError, match="STREAM_DENIAL_NOT_PINNED"):
        verify_boundary(
            completion_audit(tmp_path),
            NONCE,
            tmp_path,
            ["view_file"],
            diagnostic=True,
            stream_completions=[step],
        )


@pytest.mark.parametrize(
    "fault",
    [
        "missing_type",
        "unsafe_type",
        "non_string_type",
        "non_string_message",
        "extra_field",
        "missing_error",
        "non_object_error",
    ],
)
def test_pinned_message_does_not_override_invalid_error_shape(tmp_path, fault):
    step = pinned_error_completion()
    error = step["tool_info"]["error"]
    if fault == "missing_type":
        error.pop("type")
    elif fault == "unsafe_type":
        error["type"] = "not a safe type"
    elif fault == "non_string_type":
        error["type"] = 7
    elif fault == "non_string_message":
        error["message"] = [error["message"]]
    elif fault == "extra_field":
        error["unknown"] = True
    elif fault == "missing_error":
        step["tool_info"].pop("error")
    else:
        step["tool_info"]["error"] = error["message"]
    with pytest.raises(ValueError, match="CONTRADICTS_DENIAL"):
        verify_boundary(
            completion_audit(tmp_path),
            NONCE,
            tmp_path,
            ["view_file"],
            diagnostic=True,
            stream_completions=[step],
        )


@pytest.mark.parametrize("output", ["data", 0, False, {}, [], ["data"]])
def test_exact_error_with_nonempty_or_undocumented_output_is_rejected(tmp_path, output):
    step = pinned_error_completion()
    step["tool_info"]["output"] = output
    with pytest.raises(ValueError, match="CONTRADICTS_DENIAL"):
        verify_boundary(
            completion_audit(tmp_path),
            NONCE,
            tmp_path,
            ["view_file"],
            diagnostic=True,
            stream_completions=[step],
        )


@pytest.mark.parametrize(
    "fault",
    [
        "no_pre",
        "wrong_conv",
        "wrong_step",
        "wrong_params",
        "wrong_tool",
        "duplicate_stream",
        "duplicate_pre_and_post",
        "extra_post",
        "successful_post",
        "unknown_post",
    ],
)
def test_exact_error_requires_unique_matching_pre_and_no_conflicting_evidence(tmp_path, fault):
    audit = completion_audit(tmp_path)
    step = pinned_error_completion()
    steps = [step]
    if fault == "no_pre":
        audit.pop(2)
    elif fault == "wrong_conv":
        step["conversation_id"] = "foreign"
    elif fault == "wrong_step":
        step["step_index"] = 3
    elif fault == "wrong_params":
        step["tool_info"]["parameters"] = {"other": "value"}
    elif fault == "wrong_tool":
        step["tool_name"] = step["tool_info"]["name"] = "run_command"
    elif fault == "duplicate_stream":
        steps.append(copy.deepcopy(step))
    elif fault == "duplicate_pre_and_post":
        audit.extend(copy.deepcopy(audit[2:]))
    elif fault == "extra_post":
        audit.append({**audit[-1], "step_index": 3})
    elif fault == "successful_post":
        audit[-1].update(error_present=False, denial_observed=False)
    else:
        audit[-1].update(error_present=None, denial_observed=None)
    with pytest.raises(ValueError):
        verify_boundary(
            audit, NONCE, tmp_path, ["view_file"], diagnostic=True, stream_completions=steps
        )


def test_post_and_exact_stream_are_corroboration_not_two_attempts(tmp_path):
    assert verify_boundary(
        completion_audit(tmp_path),
        NONCE,
        tmp_path,
        ["view_file"],
        diagnostic=True,
        stream_completions=[pinned_error_completion()],
    ) == ["view_file"]


def test_stream_only_without_trusted_pre_and_pre_only_both_fail(tmp_path):
    audit = completion_audit(tmp_path)
    with pytest.raises(ValueError):
        verify_boundary(
            audit[:2],
            NONCE,
            tmp_path,
            ["view_file"],
            diagnostic=True,
            stream_completions=[pinned_error_completion()],
        )
    with pytest.raises(ValueError):
        verify_boundary(audit[:-1], NONCE, tmp_path, ["view_file"], diagnostic=True)


def test_research_still_rejects_even_exact_preblocked_error_completion(tmp_path):
    with pytest.raises(ValueError, match="RESEARCH_EXTERNAL_TOOL_ATTEMPT"):
        verify_boundary(
            completion_audit(tmp_path)[:-1],
            NONCE,
            tmp_path,
            ["view_file"],
            diagnostic=False,
            stream_completions=[pinned_error_completion()],
        )


@pytest.mark.parametrize("output", ["actual output", 0, False, {}, [], ["result"]])
def test_any_non_documented_empty_output_contradicts_even_trusted_post(tmp_path, output):
    step = terminal_tool_completion()
    step["tool_info"]["output"] = output
    with pytest.raises(ValueError, match="CONTRADICTS_DENIAL"):
        verify_boundary(
            completion_audit(tmp_path),
            NONCE,
            tmp_path,
            ["view_file"],
            diagnostic=True,
            stream_completions=[step],
        )


@pytest.mark.parametrize("output", [None, ""])
def test_only_explicit_absent_or_empty_string_output_is_treated_as_empty(output):
    step = terminal_tool_completion()
    step["tool_info"]["output"] = output
    assert summarize_tool_completion(step)["output_empty"] is True


@pytest.mark.parametrize(
    "fault", ["duplicate", "wrong_conv", "wrong_step", "wrong_params", "active", "success"]
)
def test_stream_completion_must_match_one_pre_and_cannot_mask_success(tmp_path, fault):
    step = terminal_tool_completion()
    if fault == "wrong_conv":
        step["conversation_id"] = "another-conversation"
    elif fault == "wrong_step":
        step["step_index"] = 3
    elif fault == "wrong_params":
        step["tool_info"]["parameters"] = {"different": "argument"}
    elif fault == "active":
        step["state"] = "ACTIVE"
    elif fault == "success":
        step["tool_info"].pop("error")
    with pytest.raises(ValueError):
        verify_boundary(
            completion_audit(tmp_path),
            NONCE,
            tmp_path,
            ["view_file"],
            diagnostic=True,
            stream_completions=[step, copy.deepcopy(step)] if fault == "duplicate" else [step],
        )


def test_nested_stream_tool_nodes_cannot_hide_behind_an_unknown_name():
    value = {
        "trajectory": [
            {"nested": {"step_type": "tool", "tool_info": {"name": "view_file"}}},
            {"step_type": "tool"},
        ]
    }
    names = [tool_name(node) for node in tool_nodes(value)]
    assert names == ["view_file", None]


@pytest.mark.parametrize("kind", ["user_input", "agent_response", "checkpoint"])
@pytest.mark.parametrize("state", ["ACTIVE", "DONE"])
def test_documented_non_tool_steps_are_validated_without_mutating_input(kind, state):
    step = {
        "conversation_id": "owned-conversation",
        "step_index": 0,
        "state": state,
        "step_type": kind,
    }
    before = copy.deepcopy(step)
    assert validate_step(step) is step
    assert step == before


@pytest.mark.parametrize("name", ["finish", "view_file"])
def test_a_documented_tool_shape_does_not_itself_grant_execution(name):
    step = {
        "conversation_id": "owned-conversation",
        "step_index": 1,
        "state": "DONE",
        "step_type": "tool",
        "tool_name": name,
        "tool_info": {"name": name, "parameters": {}, "error": "permission denied"},
    }
    before = copy.deepcopy(step)
    assert validate_step(step) is step
    assert step == before
    if name != "finish":
        assert list(tool_nodes(step)) == [step]


@pytest.mark.parametrize(
    "field,value",
    [
        ("step_type", "hidden_retrieval"),
        ("state", "PENDING"),
        ("step_type", []),
        ("state", {}),
        ("conversation_id", None),
        ("conversation_id", ""),
        ("step_index", None),
        ("step_index", True),
        ("step_index", -1),
        ("provider_action", "unrecognized protocol"),
        ("subagent_info", {"name": "external-agent"}),
        ("tool_name", "view_file"),
        ("tool_info", {"name": "view_file", "parameters": {}}),
    ],
)
def test_unknown_or_mixed_non_tool_payloads_fail_closed(field, value):
    step = {
        "conversation_id": "owned-conversation",
        "step_index": 0,
        "state": "DONE",
        "step_type": "agent_response",
        field: value,
    }
    with pytest.raises(ValueError):
        validate_step(step)


@pytest.mark.parametrize(
    "fault",
    [
        "no_info",
        "wrong_name",
        "extra_field",
        "missing_parameters",
        "invalid_parameters",
        "empty_name",
    ],
)
def test_tool_steps_require_a_consistent_name_and_parameter_object(fault):
    step = {
        "conversation_id": "owned-conversation",
        "step_index": 1,
        "state": "ACTIVE",
        "step_type": "tool",
        "tool_name": "view_file",
        "tool_info": {"name": "view_file", "parameters": {}},
    }
    if fault == "no_info":
        step.pop("tool_info")
    elif fault == "wrong_name":
        step["tool_info"]["name"] = "run_command"
    elif fault == "extra_field":
        step["tool_info"]["outside_execution"] = True
    elif fault == "missing_parameters":
        step["tool_info"].pop("parameters")
    elif fault == "invalid_parameters":
        step["tool_info"]["parameters"] = ["unexpected"]
    else:
        step["tool_name"] = step["tool_info"]["name"] = ""
    with pytest.raises(ValueError):
        validate_step(step)


def test_audit_reader_rejects_missing_and_symlink_files(tmp_path):
    assert read_audit(tmp_path / "absent") == []
    actual = tmp_path / "real"
    actual.write_text('{"event":"session"}\n')
    linked = tmp_path / "linked"
    linked.symlink_to(actual)
    assert read_audit(linked) == []


def hook_fixture(tmp_path, *, max_invocations=3):
    script = tmp_path / "guard.py"
    shutil.copyfile(HOOK_SOURCE, script)
    protected = tmp_path / "settings-canary.json"
    protected.write_text('{"synthetic":true}')
    audit = tmp_path / "audit.jsonl"
    config = {
        "nonce": NONCE,
        "audit_path": str(audit),
        "protected_hashes": {str(protected): hashlib.sha256(protected.read_bytes()).hexdigest()},
        "max_model_invocations": max_invocations,
    }
    (tmp_path / "guard.json").write_bytes(encoded(config))
    return script, protected, audit


def run_hook(script, event, payload):
    process = subprocess.run(
        [sys.executable, str(script), event],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    return process.returncode, json.loads(process.stdout)


def hook_payload(tmp_path, **extra):
    return {
        "conversationId": "synthetic-conversation",
        "workspacePaths": [str(tmp_path)],
        "modelName": MODEL,
        "invocationNum": 0,
        **extra,
    }


@pytest.mark.parametrize(
    "name",
    [
        "view_file",
        "run_command",
        "search_web",
        "call_mcp_tool",
        "invoke_subagent",
        "unknown-tool",
        None,
    ],
)
def test_standalone_pre_hook_denies_every_external_or_unknown_tool(tmp_path, name):
    script, _, audit = hook_fixture(tmp_path)
    code, output = run_hook(script, "pre", hook_payload(tmp_path, toolCall={"name": name}))
    assert code == 0
    assert output["decision"] == "deny"
    record = json.loads(audit.read_text())
    assert record["decision"] == "deny"
    assert record["nonce"] == NONCE
    assert record["configuration_matches"] is True


def test_only_finish_is_allowed_with_unchanged_configuration(tmp_path):
    script, protected, _ = hook_fixture(tmp_path)
    code, output = run_hook(script, "pre", hook_payload(tmp_path, toolCall={"name": "finish"}))
    assert code == 0 and output["decision"] == "allow"
    protected.write_text("changed by another writer")
    code, output = run_hook(script, "pre", hook_payload(tmp_path, toolCall={"name": "finish"}))
    assert code == 0 and output["decision"] == "deny"


def test_configuration_drift_terminates_before_model_invocation_without_leaking_contents(tmp_path):
    script, protected, audit = hook_fixture(tmp_path)
    protected.write_text("private-setting-canary-value")
    code, output = run_hook(script, "invocation", hook_payload(tmp_path))
    assert code == 0
    assert output["terminationBehavior"] == "terminate"
    record = json.loads(audit.read_text())
    assert record["blocked"] is True and record["configuration_matches"] is False
    assert "private-setting-canary-value" not in audit.read_text()
    assert "drift_path_hashes" in record


@pytest.mark.parametrize("number", [None, True, "0", -1, 3, 99])
def test_unknown_or_exhausted_hook_invocation_counter_terminates(tmp_path, number):
    script, _, audit = hook_fixture(tmp_path)
    code, output = run_hook(script, "invocation", hook_payload(tmp_path, invocationNum=number))
    assert code == 0
    assert output["terminationBehavior"] == "terminate"
    assert json.loads(audit.read_text())["blocked"] is True


def test_hook_does_not_store_raw_user_input_tool_arguments_or_secret_errors(tmp_path):
    script, _, audit = hook_fixture(tmp_path)
    payload = hook_payload(
        tmp_path,
        lastUserInput="RAW_USER_INPUT_SECRET_MARKER",
        toolCall={"name": "view_file", "args": {"ApiKey": "RAW_ARGS_SECRET_MARKER"}},
        error="Permission denied: RAW_ERROR_SECRET_MARKER",
    )
    run_hook(script, "pre", payload)
    run_hook(script, "post", payload)
    raw = audit.read_text()
    for text in (
        "RAW_USER_INPUT_SECRET_MARKER",
        "RAW_ARGS_SECRET_MARKER",
        "RAW_ERROR_SECRET_MARKER",
        "lastUserInput",
        "ApiKey",
    ):
        assert text not in raw
    records = [json.loads(line) for line in raw.splitlines()]
    assert records[0]["args_sha256"] == sha(encoded(payload["toolCall"]["args"]))
    assert records[1]["denial_observed"] is True
    assert records[1]["error_sha256"]


def test_hook_failure_is_never_an_allow_fallback(tmp_path):
    script, _, _ = hook_fixture(tmp_path)
    (tmp_path / "guard.json").unlink()
    code, output = run_hook(script, "pre", hook_payload(tmp_path, toolCall={"name": "finish"}))
    assert code == 2 and output["decision"] == "deny"
    code, output = run_hook(script, "invocation", hook_payload(tmp_path))
    assert code == 2 and output["terminationBehavior"] == "terminate"
