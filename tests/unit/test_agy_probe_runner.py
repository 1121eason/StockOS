"""Fake local processes only: these tests never invoke AGY or a model."""

import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "probe_agy_explanation",
    Path(__file__).resolve().parents[2] / "scripts/probe_agy_explanation.py",
)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def init(**overrides):
    return {
        "event": "init",
        "init": {
            "agent": probe.AGENT,
            "model": probe.MODEL,
            "tools": ["finish"],
            "permission_mode": "strict",
            **overrides,
        },
    }


def result(output):
    return {"event": "result", "result": {"status": "SUCCESS", "structured_output": output}}


def fake_cli(tmp_path, monkeypatch, events, *, delayed_write=False):
    path = tmp_path / "fake-agy"
    content = (
        f"#!{sys.executable}\nimport sys,time\nfrom pathlib import Path\nsys.stdin.readline()\n"
    )
    content += "\n".join("print(" + repr(json.dumps(event)) + ",flush=True)" for event in events)
    if delayed_write:
        content += "\ntime.sleep(3)\nPath('should-not-exist').touch()\n"
    path.write_text(content)
    path.chmod(0o700)
    monkeypatch.setattr(probe, "CLI", path)
    work = tmp_path / "work"
    work.mkdir()
    return work


def test_safe_synthetic_response_preserves_strict_identity_and_no_financial_input(
    tmp_path, monkeypatch
):
    work = fake_cli(tmp_path, monkeypatch, [init(), result({"ok": True})])
    answer = probe.synthetic_call(work, "synthetic", {"ok": True})
    assert answer["status"] == "PASS"
    assert answer["financial_documents_sent"] == 0
    assert answer["global_settings_modified"] is False
    assert answer["owned_process_group_absent"] is True


def test_boolean_constant_is_not_interchangeable_with_integer(tmp_path, monkeypatch):
    work = fake_cli(tmp_path, monkeypatch, [init(), result({"ok": 1})])
    answer = probe.synthetic_call(work, "synthetic", {"ok": True})
    assert answer["status"] == "FAIL"
    assert answer["reason"] == "UNSUPPLIED_CONTENT_OR_SCHEMA_MISMATCH"
    assert answer["structured_output"] is None


@pytest.mark.parametrize("permission", ["always-proceed", None])
def test_unsafe_or_unverifiable_permission_mode_is_not_accepted(tmp_path, monkeypatch, permission):
    work = fake_cli(tmp_path, monkeypatch, [init(permission_mode=permission)], delayed_write=True)
    before = time.monotonic()
    answer = probe.synthetic_call(work, "synthetic", {"ok": True})
    assert time.monotonic() - before < 2
    assert answer["reason"] == "AGY_PERMISSION_MODE_NOT_STRICT"
    assert answer["structured_output"] is None
    assert not (work / "should-not-exist").exists()


def test_advertised_external_tools_abort_before_terminal_answer(tmp_path, monkeypatch):
    work = fake_cli(
        tmp_path, monkeypatch, [init(tools=["finish", "view_file"])], delayed_write=True
    )
    answer = probe.synthetic_call(work, "synthetic", {"ok": True})
    assert answer["reason"] == "AGY_NO_EXTERNAL_TOOLS_CONTRACT_UNVERIFIED"
    assert answer["advertised_tools"] == ["finish", "view_file"]
    assert answer["owned_process_group_absent"] is True
    assert not (work / "should-not-exist").exists()


def test_nested_tool_attempt_is_stopped_in_live_loop_not_after_waiting(tmp_path, monkeypatch):
    event = {
        "event": "step_update",
        "step_update": {
            "trajectory": [
                {
                    "step_type": "tool",
                    "tool_info": {"name": "run_command"},
                }
            ]
        },
    }
    work = fake_cli(tmp_path, monkeypatch, [init(), event], delayed_write=True)
    before = time.monotonic()
    answer = probe.synthetic_call(work, "synthetic", {"ok": True})
    assert time.monotonic() - before < 2
    assert answer["reason"] == "EXTERNAL_TOOL_ATTEMPT"
    assert answer["structured_output"] is None
    assert not (work / "should-not-exist").exists()


def test_existing_diagnostic_receipt_stops_before_reserving_or_launching(tmp_path, monkeypatch):
    fake = tmp_path / "binary"
    fake.write_bytes(b"nonexecuted fake")
    monkeypatch.setattr(probe, "CLI", fake)
    monkeypatch.setattr(probe, "CLI_SHA", hashlib.sha256(fake.read_bytes()).hexdigest())
    output = tmp_path / "output"
    output.mkdir()
    (output / "diagnostic-0001.json").write_text("retained")
    monkeypatch.setattr(
        sys, "argv", ["probe", "--output-dir", str(output), "--state-root", str(tmp_path / "state")]
    )
    with pytest.raises(SystemExit, match="Existing qualification retained"):
        probe.main()
    assert (output / "diagnostic-0001.json").read_text() == "retained"
    assert not (tmp_path / "state").exists()
