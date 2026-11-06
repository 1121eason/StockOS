"""Offline preflight for the newly authorized permission-test continuation."""

import importlib.util
import json
from pathlib import Path

import pytest

from valuation_engine.ai import agy_guarded
from valuation_engine.ai.agy_guarded import (
    AGENT,
    DENIED_CHILD,
    MODEL,
    GuardedTransport,
    validate_identity,
)


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[2] / "scripts/run_agy_permission_continuation.py"
    spec = importlib.util.spec_from_file_location("permission_continuation_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "default,agent,valid",
    [
        (True, None, True),
        (True, "default", True),
        (True, "builtin", True),
        (True, [], False),
        (False, AGENT, True),
        (False, None, False),
        (False, "builtin", False),
    ],
)
def test_diagnostic_default_and_exact_production_identity(default, agent, valid):
    init = {"agent": agent, "model": MODEL, "permission_mode": "strict", "tools": []}
    if valid:
        validate_identity(init, default_agent=default)
    else:
        with pytest.raises(ValueError):
            validate_identity(init, default_agent=default)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "other-model"),
        ("permission_mode", "always-proceed"),
        ("permission_mode", "request-review"),
        ("tools", None),
    ],
)
def test_default_actor_never_relaxes_model_or_strict_mode(field, value):
    init = {"model": MODEL, "permission_mode": "strict", "tools": []}
    init[field] = value
    with pytest.raises(ValueError):
        validate_identity(init, default_agent=True)


def test_default_diagnostic_launch_has_no_custom_parent_and_still_protects_child(
    tmp_path, monkeypatch
):
    hook = tmp_path / "hook.py"
    hook.write_text("# offline fixture")
    monkeypatch.setattr(agy_guarded, "HOOK", hook)
    monkeypatch.setattr(agy_guarded, "subscription_environment", lambda: {})
    observed = {}

    def intercept(argv, **kwargs):
        observed["argv"] = argv
        raise RuntimeError("INTERCEPTED_NO_PROCESS")

    monkeypatch.setattr(agy_guarded.subprocess, "Popen", intercept)
    cwd = tmp_path / "workspace"
    cwd.mkdir()
    t = GuardedTransport(
        output=tmp_path,
        budget=None,
        policy_hash="synthetic",
        protected_hashes={},
        denied_roots=[],
        diagnostic_default_agent=True,
    )
    with pytest.raises(RuntimeError, match="INTERCEPTED_NO_PROCESS"):
        t._call(
            cwd,
            {"task": "synthetic", "untrusted_data": {}, "response_schema": {"type": "object"}},
            diagnostic=True,
            timeout=1,
        )
    assert "--agent" not in observed["argv"]
    assert not (cwd / ".agents/agents" / AGENT / "agent.md").exists()
    child = cwd / ".agents/agents" / DENIED_CHILD / "agent.md"
    guard = json.loads((cwd / "guard.json").read_text())
    assert guard["protected_hashes"][str(child)] == agy_guarded.file_sha(child)


def test_new_authorization_is_immutable_and_keeps_predecessor_fingerprints(tmp_path, runner):
    prior = tmp_path / "prior"
    prior.mkdir()
    (prior / "attempt-0001.json").write_text('{"status":"FAILED"}')
    (prior / "global-active.lock").write_text("owner lease excluded from immutable data")
    fingerprints = runner.legacy_fingerprints(prior)
    assert set(fingerprints) == {"attempt-0001.json"}
    current = tmp_path / "new"
    current.mkdir()
    auth = {
        "user_instruction": "new owner task",
        "legacy_files_sha256": fingerprints,
        "caps": {"diagnostic": 4, "research": 22},
    }
    runner.immutable_authorization(current, auth)
    raw = (current / "authorization.json").read_bytes()
    runner.immutable_authorization(current, auth)
    with pytest.raises(ValueError, match="CONTINUATION_AUTHORIZATION_DRIFT"):
        runner.immutable_authorization(current, {**auth, "user_instruction": "changed"})
    assert (current / "authorization.json").read_bytes() == raw
    assert runner.legacy_fingerprints(prior) == fingerprints


def test_complete_negative_gate_then_exact_production_profile_before_qualification(
    tmp_path, runner, monkeypatch
):
    calls = []
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    hook = tmp_path / "hook.py"
    hook.write_text("synthetic protected hook")
    monkeypatch.setattr(runner, "HOOK", hook)
    paths = ["src/valuation_engine/ai/agy_guarded.py", "src/valuation_engine/ai/agy_policy.py"]
    for name in paths:
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("synthetic frozen source")
    first = tmp_path / "outputs/agy-permissions-completion-20261106"
    (first / "attempt-0001").mkdir(parents=True)
    (first / "attempt-0001/result.json").write_text("{}")
    (first / "native-denial-rows.json").write_text(
        json.dumps({"global_installed_sha256": {}, "hook_sha256": agy_guarded.file_sha(hook)})
    )
    (first / "contract.json").write_text(
        json.dumps({"code_sha256": {name: agy_guarded.file_sha(tmp_path / name) for name in paths}})
    )
    second = tmp_path / "outputs/agy-permissions-completion-20261106-v2"
    (second / "attempt-0002").mkdir(parents=True)
    (second / "attempt-0002/result.json").write_text("{}")
    (second / "native-readonly-denial-rows.json").write_bytes(
        (first / "native-denial-rows.json").read_bytes()
    )
    (second / "contract.json").write_bytes((first / "contract.json").read_bytes())
    native_names = ("run_command", "write_file", "invoke_subagent")
    monkeypatch.setattr(
        runner,
        "validate_permission_evidence",
        lambda *args, readonly=False: [{"tool_name": name} for name in (
            ("view_file", "read_url_content", "search_web") if readonly else native_names
        )],
    )

    class Transport:
        def __init__(self):
            self.output = tmp_path
            self.budget = None
            self.policy_hash = "synthetic-policy"
            self.protected_hashes = {}
            self.denied_roots = []

        def request(self, name, prompt, **kwargs):
            calls.append((name, kwargs))
            expected = {
                "answer": "unavailable",
                "quote": prompt["untrusted_data"]["sentence"],
                "limitation": "synthetic_only",
            }
            with pytest.raises(ValueError, match="SYNTHETIC_EXACT_OUTPUT_MISMATCH"):
                kwargs["validate"]({**expected, "quote": "wrong"})
            kwargs["validate"](expected)
            return expected, {"denied_tools": [], "actual_agent": AGENT}

    transport = Transport()
    monkeypatch.setattr(runner, "GuardedTransport", lambda **kwargs: transport)
    targets = {
        key: tmp_path / key for key in ("outside", "head", "database", "marker", "write_marker")
    }
    result = runner.qualify(transport, targets, tmp_path, "synthetic-policy")
    assert len(calls) == 1
    assert set(result["negative_tools"]) == {
        "view_file",
        "read_url_content",
        "search_web",
        *native_names,
    }
    assert calls[0][1]["use_research_profile"] is True
    assert calls[0][1]["forbid_external_tools"] is True
    assert result["financial_documents_sent"] == 0
    assert result["status"] == "PASS_CONTROLLED_BOUNDARY"
