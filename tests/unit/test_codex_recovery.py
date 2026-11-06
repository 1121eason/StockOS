"""Regression tests for Codex recovery boundaries; all subprocesses are synthetic."""

import concurrent.futures
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from valuation_engine.ai import attempt_journal, codex_pit
from valuation_engine.ai.attempt_journal import (
    AttemptInProgress,
    AttemptJournal,
    write_immutable_json,
    write_json_atomic,
)
from valuation_engine.ai.provider import ProviderUnavailable

PILOT_SCRIPT = Path(__file__).resolve().parents[2] / "scripts/run_codex_pilot_v5.py"
PILOT_SPEC = importlib.util.spec_from_file_location("run_codex_pilot_v5", PILOT_SCRIPT)
assert PILOT_SPEC and PILOT_SPEC.loader
run_codex_pilot_v5 = importlib.util.module_from_spec(PILOT_SPEC)
PILOT_SPEC.loader.exec_module(run_codex_pilot_v5)


class NeverStopsProcess:
    """A Popen stand-in whose bounded waits time out and whose streams are real FDs."""

    pid = 914203
    returncode = None

    def __init__(self):
        _, stdin_write = os.pipe()
        stdout_read, stdout_write = os.pipe()
        stderr_read, stderr_write = os.pipe()
        os.close(stdout_write)
        os.close(stderr_write)
        self.stdin = os.fdopen(stdin_write, "wb", buffering=0)
        self.stdout = os.fdopen(stdout_read, "rb", buffering=0)
        self.stderr = os.fdopen(stderr_read, "rb", buffering=0)
        self.wait_timeouts = []

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        if timeout is None:
            raise AssertionError("unbounded wait attempted")
        raise subprocess.TimeoutExpired("synthetic-process", timeout)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.wait()


def test_v6_profile_keeps_fixed_inputs_and_v5_version_pin(monkeypatch):
    import importlib

    monkeypatch.syspath_prepend(str(PILOT_SCRIPT.parent))
    v6 = importlib.import_module("run_codex_pilot_v6")
    before = dict(v6.runner.EXPECTED_Q2_INPUTS)
    actual = {**before, "prompt_version": "PromptSetV6"}
    compare = v6.runner.compare_q2_input_summary
    assert compare(actual)["status"] == "FAIL"
    assert compare(actual, expected_prompt_version=v6.EXPECTED_PROMPT_VERSION)["status"] == "PASS"
    for key in ("package_hash", "information_cutoff", "source_document_ids", "requested_model"):
        changed = {**actual, key: "drift"}
        assert compare(changed, expected_prompt_version=v6.EXPECTED_PROMPT_VERSION)["status"] == "FAIL"
    captured = {}
    monkeypatch.setattr(v6.runner, "main", lambda argv, **kw: captured.update(argv=argv, **kw))
    v6.main(["--isolation-receipt", "synthetic", "--kernel-receipt", "synthetic"])
    assert captured["expected_prompt_version"] == "PromptSetV6"
    assert captured["purpose"] == "codex_pit_q2_v6_pilot"
    assert v6.runner.EXPECTED_Q2_INPUTS == before


class JournalThatFailsOnInference:
    process_state_unknown = False

    def __init__(self):
        self.events = []

    def emit(self, event, **details):
        self.events.append((event, details))
        if event == "inference_started":
            raise OSError("synthetic journal write failure")

    def mark_process_state_unknown(self):
        self.process_state_unknown = True


def install_never_stops_process(monkeypatch, process):
    monkeypatch.setattr(codex_pit.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(codex_pit, "subscription_environment", lambda: {})
    monkeypatch.setattr(codex_pit.os, "killpg", lambda _pid, _sig: None)


def test_termination_unknown_never_calls_unbounded_wait(monkeypatch, tmp_path):
    process = NeverStopsProcess()
    install_never_stops_process(monkeypatch, process)

    result = codex_pit.monitor(["fake"], "", tmp_path, 1, journal=None)

    assert result["failure_kind"] == "termination_unconfirmed"
    assert result["exit_code"] is None
    assert process.wait_timeouts == [2, 5]
    assert len(result["runner_termination_requests"]) == 1
    assert result["runner_termination_requests"][0]["trigger"] == "bounded_wait_timeout"
    assert result["wait_results"][0]["result"] == "timed_out"
    assert process.stdin.closed and process.stdout.closed and process.stderr.closed


def test_unknown_termination_supersedes_a_monitor_exception_with_explicit_status(monkeypatch, tmp_path):
    process = NeverStopsProcess()
    install_never_stops_process(monkeypatch, process)

    class SelectorThatFails:
        def __init__(self):
            self.registered = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def register(self, stream, _event, name):
            self.registered[stream] = name

        def get_map(self):
            return self.registered

        def select(self, _timeout):
            raise OSError("synthetic selector failure")

        def unregister(self, stream):
            self.registered.pop(stream, None)

    monkeypatch.setattr(codex_pit.selectors, "DefaultSelector", SelectorThatFails)
    result = codex_pit.monitor(["fake"], "", tmp_path, 1)

    assert result["failure_kind"] == "termination_unconfirmed"
    assert result["exit_code"] is None
    assert process.wait_timeouts == [2, 5]
    assert all(timeout is not None for timeout in process.wait_timeouts)


def test_journal_write_failure_still_uses_bounded_process_cleanup(monkeypatch, tmp_path):
    process = NeverStopsProcess()
    journal = AttemptJournal(tmp_path / "attempts", purpose="journal-write-failure")
    original_emit = journal.emit

    def failing_emit(event, **details):
        if event == "inference_started":
            raise OSError("synthetic journal write failure")
        return original_emit(event, **details)

    monkeypatch.setattr(journal, "emit", failing_emit)
    install_never_stops_process(monkeypatch, process)

    with pytest.raises(OSError, match="synthetic journal write failure"):
        codex_pit.monitor(["fake"], "", tmp_path, 1, journal=journal)

    assert journal.process_state_unknown
    assert process.wait_timeouts == [2, 5]
    assert all(timeout is not None for timeout in process.wait_timeouts)
    assert process.stdin.closed and process.stdout.closed and process.stderr.closed
    journal.finish(status="unknown", failure_kind="termination_unconfirmed")
    assert journal.lock_path.exists()
    with pytest.raises(AttemptInProgress):
        AttemptJournal(journal.attempts_dir, purpose="blocked-after-journal-failure")


def test_pilot_save_refuses_to_overwrite_a_completed_receipt(tmp_path):
    receipt = tmp_path / "pilot.json"
    failed = {"gate": "FAIL", "reason": "synthetic"}
    passed = {"gate": "PASS"}
    run_codex_pilot_v5.save(receipt, failed)
    original = receipt.read_bytes()
    original_hash = hashlib.sha256(original).hexdigest()

    with pytest.raises(FileExistsError):
        run_codex_pilot_v5.save(receipt, passed)

    assert receipt.read_bytes() == original
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == original_hash


def load_script(name):
    path = Path(__file__).resolve().parents[2] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_gate():
    return {
        "gate": "PASS",
        "gates": {f"C{index}": "PASS" for index in range(1, 13)},
        "policy_hash": codex_pit.POLICY_HASH,
        "transport_policy": codex_pit.POLICY,
        "model": codex_pit.MODEL,
        "historical_data_sent": False,
        "configuration_unchanged": True,
        "configuration_hash_before": "synthetic-config-hash",
        "configuration_hash_after": "synthetic-config-hash",
    }


def test_normal_fake_cli_completes_and_journals_lifecycle(monkeypatch, tmp_path):
    executable = tmp_path / "fake-codex"
    completed = {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":true}'}}
    executable.write_text(
        "#!" + sys.executable + "\n"
        + "import json\n"
        + "print(json.dumps(" + repr(completed) + "), flush=True)\n"
        + "print(json.dumps({'type':'turn.completed'}), flush=True)\n"
    )
    executable.chmod(0o700)
    monkeypatch.setattr(codex_pit, "subscription_environment", lambda: {})
    journal = AttemptJournal(tmp_path / "attempts", purpose="synthetic-normal-cli")

    result = codex_pit.call(
        {
            "system": "Synthetic only",
            "task": "Return the fixed JSON object",
            "untrusted_data": {"synthetic": True},
            "response_schema": {"type": "object"},
        },
        str(executable),
        timeout=5,
        journal=journal,
    )
    journal.finish(status="completed")

    records = [json.loads(line) for line in journal.progress_path.read_text().splitlines()]
    assert result["structured_output"] == {"ok": True}
    assert result["failure_kind"] is None
    assert [
        row["event"]
        for row in records
        if row["event"] in {"runner_started", "inference_started", "stage_completed"}
    ] == ["runner_started", "inference_started", "stage_completed"]
    assert records[-1]["status"] == "completed"
    assert result["exit_code"] == 0
    assert result["observed_exit_code"] == 0
    assert result["runner_termination_requests"] == []
    assert result["wait_results"][0]["result"] == "completed"
    assert not journal.lock_path.exists()


def fake_probe_cli(tmp_path, events, *, sleep_after=False):
    executable = tmp_path / "fake-codex-for-probe"
    lines = [
        "import json,os,signal,sys,time",
        *[f"print({json.dumps(json.dumps(event))}, flush=True)" for event in events],
    ]
    if sleep_after:
        lines.append("time.sleep(30)")
    executable.write_text("#!" + sys.executable + "\n" + "\n".join(lines) + "\n")
    executable.chmod(0o700)
    return executable


def configure_probe_script(monkeypatch, tmp_path, executable):
    probe = load_script("probe_codex_pit_launch.py")
    output = tmp_path / "probe-output"
    monkeypatch.setattr(probe, "OUT", output)
    monkeypatch.setattr(probe, "workspace_fingerprint", lambda _root: {"synthetic": True})
    monkeypatch.setattr(codex_pit, "subscription_environment", lambda: {})

    class SyntheticProvider:
        def __init__(self, *_args, **_kwargs):
            self.executable = str(executable)

        def check(self):
            return {
                "reason": "PIT_PROBES_REQUIRED",
                "cli_version": codex_pit.VERSION,
                "authenticated": True,
            }

    monkeypatch.setattr(probe, "CodexCLIProvider", SyntheticProvider)
    return probe, output


@pytest.mark.parametrize("event_type", ["error", "turn.failed"])
def test_probe_persists_first_cli_error_and_runner_cleanup_without_secrets(
    monkeypatch, tmp_path, event_type
):
    secret = "synthetic-private-diagnostic-token"
    error = {
        "type": event_type,
        "error": {
            "code": "UPSTREAM_BUSY",
            "status": 503,
            "message": (
                f"provider rejected Bearer {secret} API_TOKEN={secret} "
                f"https://example.invalid/path?token={secret} "
                + "x" * 300
            ),
        },
    }
    events = [{"type": "notice", "index": index} for index in range(34)] + [error]
    executable = fake_probe_cli(tmp_path, events, sleep_after=True)
    probe, output = configure_probe_script(monkeypatch, tmp_path, executable)

    exit_status = probe.main()

    assert exit_status == 1
    attempts = output / "attempts"
    attempt_dirs = [path for path in attempts.iterdir() if path.is_dir()]
    assert len(attempt_dirs) == 1
    attempt = attempt_dirs[0]
    receipt = json.loads((attempt / "probe.json").read_text())
    diagnostics_path = output / receipt["diagnostic_receipt"]["path"]
    diagnostic_bytes = diagnostics_path.read_bytes()
    assert hashlib.sha256(diagnostic_bytes).hexdigest() == receipt["diagnostic_receipt"]["sha256"]
    diagnostic = json.loads(diagnostic_bytes)

    assert receipt["gate"] == "FAIL"
    assert receipt["failure_kind"] == "provider_failure"
    assert diagnostic["observed_exit_code"] == -9
    assert diagnostic["process_state"] == "confirmed_stopped"
    assert diagnostic["events_seen"] == 35
    assert len(diagnostic["events"]) == codex_pit.MAX_DIAGNOSTIC_EVENTS
    assert diagnostic["events_truncated"] is True
    first = diagnostic["first_failure"]
    assert first["kind"] == "provider_failure"
    assert first["event_type"] == event_type
    assert first["sequence"] == 35
    assert first["error_code"] == "UPSTREAM_BUSY"
    assert first["http_status"] == 503
    assert first["summary_truncated"] is True
    assert len(first["summary"]) == codex_pit.MAX_ERROR_SUMMARY_CHARS
    assert secret not in attempt.joinpath("progress.jsonl").read_text()
    assert secret not in diagnostics_path.read_text()
    assert diagnostic["runner_termination_requests"]
    request = diagnostic["runner_termination_requests"][0]
    assert request["signal"] == "SIGKILL"
    assert request["trigger"] == "provider_failure"
    assert request["pre_signal_process_state"] == "running"
    assert request["syscall_result"] == "success"
    assert request["causal_attribution"] == "unknown"
    assert diagnostic["wait_results"][0]["result"] == "completed"
    assert diagnostic["wait_results"][0]["exit_code"] == -9
    assert not (attempts / "active.lock").exists()


def test_probe_success_returns_zero_and_binds_immutable_diagnostic_receipt(monkeypatch, tmp_path):
    events = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":true}'}},
        {"type": "turn.completed"},
    ]
    executable = fake_probe_cli(tmp_path, events)
    probe, output = configure_probe_script(monkeypatch, tmp_path, executable)

    assert probe.main() == 0
    attempt = next(path for path in (output / "attempts").iterdir() if path.is_dir())
    receipt = json.loads((attempt / "probe.json").read_text())
    diagnostics_path = output / receipt["diagnostic_receipt"]["path"]
    assert receipt["gate"] == "PASS"
    assert hashlib.sha256(diagnostics_path.read_bytes()).hexdigest() == receipt[
        "diagnostic_receipt"
    ]["sha256"]
    diagnostics = json.loads(diagnostics_path.read_text())
    assert diagnostics["observed_exit_code"] == 0
    assert diagnostics["runner_termination_requests"] == []
    assert not (output / "attempts/active.lock").exists()


def test_probe_cli_receives_explicitly_typed_output_schema(monkeypatch, tmp_path):
    """Exercise the staged CLI file against the contract rejected by the live service."""
    executable = tmp_path / "schema-checking-codex"
    executable.write_text(
        "#!" + sys.executable + "\n"
        + """import json,sys
from pathlib import Path
schema_path = Path(sys.argv[sys.argv.index('--output-schema') + 1])
schema = json.loads(schema_path.read_text())
sys.stdin.read()
for name, node in schema['properties'].items():
    if 'type' not in node:
        print(json.dumps({'type': 'error', 'error': {
            'code': 'invalid_json_schema',
            'message': 'Property ' + name + ' must have a type key',
        }}), flush=True)
        sys.exit(1)
assert schema['properties']['ok']['type'] == 'boolean'
assert schema['properties']['ok']['const'] is True
assert schema['required'] == ['ok']
assert schema['additionalProperties'] is False
print(json.dumps({'type': 'item.completed', 'item': {
    'type': 'agent_message', 'text': '{"ok":true}',
}}), flush=True)
print(json.dumps({'type': 'turn.completed'}), flush=True)
"""
    )
    executable.chmod(0o700)
    probe, output = configure_probe_script(monkeypatch, tmp_path, executable)

    assert probe.main() == 0

    attempt = next(path for path in (output / "attempts").iterdir() if path.is_dir())
    receipt = json.loads((attempt / "probe.json").read_text())
    diagnostics = json.loads((output / receipt["diagnostic_receipt"]["path"]).read_text())
    assert receipt["gate"] == "PASS"
    assert receipt["exit_code"] == 0
    assert diagnostics["first_failure"] is None
    assert diagnostics["runner_termination_requests"] == []
    assert not (output / "attempts/active.lock").exists()


def test_probe_manifest_binds_explicit_launch_intent_bytes(monkeypatch, tmp_path):
    events = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":true}'}},
        {"type": "turn.completed"},
    ]
    executable = fake_probe_cli(tmp_path, events)
    probe, output = configure_probe_script(monkeypatch, tmp_path, executable)
    intent_path = tmp_path / "launch-intent.json"
    intent_bytes = (
        json.dumps(
            {
                "schema": "CodexPITProbeLaunchIntentV1",
                "historical_input": False,
                "intent_id": "synthetic-intent",
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()
    intent_path.write_bytes(intent_bytes)

    assert probe.main(["--launch-intent", str(intent_path)]) == 0
    attempt = next(path for path in (output / "attempts").iterdir() if path.is_dir())
    reference = json.loads((attempt / "manifest.json").read_text())["launch_intent"]
    receipt = json.loads((attempt / "probe.json").read_text())
    expected_reference = {
        "path": str(intent_path.resolve()),
        "sha256": hashlib.sha256(intent_bytes).hexdigest(),
    }
    assert reference == expected_reference
    assert receipt["launch_intent"] == expected_reference


def test_probe_launch_failure_returns_nonzero_without_invented_process_times(
    monkeypatch, tmp_path
):
    executable = fake_probe_cli(tmp_path, [])
    probe, output = configure_probe_script(monkeypatch, tmp_path, executable)

    def fail_launch(*_args, **_kwargs):
        raise PermissionError("synthetic private launch detail")

    monkeypatch.setattr(codex_pit.subprocess, "Popen", fail_launch)

    assert probe.main() == 1
    attempt = next(path for path in (output / "attempts").iterdir() if path.is_dir())
    receipt = json.loads((attempt / "probe.json").read_text())
    diagnostics = json.loads((output / receipt["diagnostic_receipt"]["path"]).read_text())
    assert receipt["gate"] == "FAIL"
    assert receipt["failure_kind"] == "process_launch_failure"
    assert receipt["started_at"] is None
    assert receipt["launch_requested_at"]
    assert receipt["exit_code"] is None
    assert diagnostics["process_state"] == "not_started"
    assert diagnostics["observed_exit_code"] is None
    assert diagnostics["launch_error_type"] == "PermissionError"
    assert diagnostics["runner_termination_requests"] == []
    assert "synthetic private launch detail" not in (attempt / "probe.json").read_text()
    assert not (output / "attempts/active.lock").exists()


def test_probe_unknown_termination_returns_nonzero_and_keeps_lock(monkeypatch, tmp_path):
    executable = fake_probe_cli(tmp_path, [])
    probe, output = configure_probe_script(monkeypatch, tmp_path, executable)
    process = NeverStopsProcess()
    install_never_stops_process(monkeypatch, process)

    assert probe.main() == 1
    attempts = output / "attempts"
    attempt = next(path for path in attempts.iterdir() if path.is_dir())
    receipt = json.loads((attempt / "probe.json").read_text())
    diagnostics = json.loads((output / receipt["diagnostic_receipt"]["path"]).read_text())
    assert receipt["gate"] == "FAIL"
    assert receipt["failure_kind"] == "termination_unconfirmed"
    assert diagnostics["process_state"] == "unknown"
    assert diagnostics["observed_exit_code"] is None
    assert [row["timeout_seconds"] for row in diagnostics["wait_results"]] == [2, 5]
    assert (attempts / "active.lock").exists()
    with pytest.raises(AttemptInProgress):
        AttemptJournal(attempts, purpose="blocked-after-probe-unknown")


def test_probe_diagnostic_write_failure_returns_nonzero_after_journal_cleanup(
    monkeypatch, tmp_path
):
    events = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":true}'}},
        {"type": "turn.completed"},
    ]
    executable = fake_probe_cli(tmp_path, events)
    probe, output = configure_probe_script(monkeypatch, tmp_path, executable)
    original_save = probe.save

    def fail_diagnostics(path, value):
        if Path(path).name == "diagnostics.json":
            raise OSError("synthetic diagnostic persistence failure")
        return original_save(path, value)

    monkeypatch.setattr(probe, "save", fail_diagnostics)

    assert probe.main() == 1
    attempts = output / "attempts"
    attempt = next(path for path in attempts.iterdir() if path.is_dir())
    records = [json.loads(line) for line in (attempt / "progress.jsonl").read_text().splitlines()]
    assert records[-2]["event"] == "probe_execution_failed"
    assert records[-2]["failure_kind"] == "diagnostic_receipt_write_failure"
    assert records[-2]["phase"] == "diagnostic_write"
    assert records[-1]["event"] == "finished"
    assert records[-1]["status"] == "failed"
    assert records[-1]["error_type"] == "OSError"
    assert not (attempt / "probe.json").exists()
    assert not (attempts / "active.lock").exists()


def test_child_self_sigkill_has_no_fabricated_runner_signal(monkeypatch, tmp_path):
    executable = tmp_path / "self-sigkill.py"
    executable.write_text(
        "import os,signal\n"
        "os.killpg(os.getpgrp(), signal.SIGKILL)\n"
    )
    monkeypatch.setattr(codex_pit, "subscription_environment", lambda: {})

    result = codex_pit.monitor([sys.executable, str(executable)], "", tmp_path, 5)

    assert result["failure_kind"] == "provider_failure"
    assert result["observed_exit_code"] == -9
    assert result["runner_termination_requests"] == []
    assert result["wait_results"][0]["result"] == "completed"


def test_process_launch_failure_has_no_inference_or_fabricated_process_fields(monkeypatch, tmp_path):
    journal = AttemptJournal(tmp_path / "attempts", purpose="synthetic-launch-failure")
    monkeypatch.setattr(codex_pit, "subscription_environment", lambda: {})

    def fail_launch(*args, **kwargs):
        raise FileNotFoundError("synthetic private message")

    monkeypatch.setattr(codex_pit.subprocess, "Popen", fail_launch)
    result = codex_pit.monitor(["missing"], "", tmp_path, 1, journal=journal)
    journal.finish(status="failed")

    records = [json.loads(line) for line in journal.progress_path.read_text().splitlines()]
    assert result["failure_kind"] == "process_launch_failure"
    assert result["launch_error_type"] == "FileNotFoundError"
    assert result["exit_code"] is None
    assert "started_at" not in result
    assert not any(row["event"] == "inference_started" for row in records)
    assert "synthetic private message" not in json.dumps(result) + journal.progress_path.read_text()
    assert not journal.lock_path.exists()


def test_unknown_termination_keeps_legacy_style_lock_and_blocks_next_attempt(monkeypatch, tmp_path):
    process = NeverStopsProcess()
    install_never_stops_process(monkeypatch, process)
    attempts = tmp_path / "attempts"
    journal = AttemptJournal(attempts, purpose="synthetic-unknown-termination")

    result = codex_pit.monitor(["fake"], "", tmp_path, 1, journal=journal)
    journal.finish(status="unknown", failure_kind="termination_unconfirmed")

    original_progress = journal.progress_path.read_bytes()
    assert result["failure_kind"] == "termination_unconfirmed"
    assert result["exit_code"] is None
    assert journal.process_state_unknown
    assert journal.lock_path.exists()
    assert "termination_unconfirmed" in original_progress.decode()
    with pytest.raises(AttemptInProgress):
        AttemptJournal(attempts, purpose="must-not-start")
    assert journal.progress_path.read_bytes() == original_progress


def test_call_retains_read_only_scratch_when_process_state_is_unknown(monkeypatch, tmp_path):
    scratch = tmp_path / "qve-codex-pit-retained"
    journal = SimpleNamespace(process_state_unknown=False)

    def make_scratch(prefix):
        assert prefix == "qve-codex-pit-"
        scratch.mkdir(mode=0o700)
        return str(scratch)

    def unknown_monitor(*args, **kwargs):
        journal.process_state_unknown = True
        return {
            "failure_kind": "termination_unconfirmed",
            "exit_code": None,
            "structured_output": None,
            "started_at": "synthetic",
            "completed_at": "synthetic",
            "raw_response_hash": "stdout-hash",
            "stderr_hash": "stderr-hash",
        }

    monkeypatch.setattr(codex_pit.tempfile, "mkdtemp", make_scratch)
    monkeypatch.setattr(codex_pit, "monitor", unknown_monitor)
    result = codex_pit.call(
        {
            "system": "Synthetic only",
            "task": "No model call",
            "untrusted_data": {"synthetic": True},
            "response_schema": {"type": "object"},
        },
        "unused-fake",
        timeout=1,
        journal=journal,
    )

    assert result["failure_kind"] == "termination_unconfirmed"
    assert result["exit_code"] is None
    receipt = result["metadata"]["working_directory_receipt"]
    assert receipt["workspace_retained_after_unconfirmed_termination"]
    assert stat.S_IMODE(scratch.stat().st_mode) == 0o500
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o400 for path in scratch.rglob("*") if path.is_file())
    for path in sorted((p for p in scratch.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        path.chmod(0o700)
    scratch.chmod(0o700)
    shutil.rmtree(scratch)


def test_real_fake_process_timeout_is_bounded_and_reaped(tmp_path):
    executable = tmp_path / "sleeping-fake-cli.py"
    pid_file = tmp_path / "child.pid"
    executable.write_text(
        "import os,sys,time\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(30)\n"
    )
    worker_code = (
        "from pathlib import Path; import json,sys; "
        "from valuation_engine.ai.codex_pit import monitor; "
        f"r=monitor([sys.executable, {str(executable)!r}, {str(pid_file)!r}], '', {str(tmp_path)!r}, 0.1); "
        "print(json.dumps({'failure_kind':r['failure_kind'],'exit_code':r['exit_code']}))"
    )
    worker = subprocess.Popen(
        [sys.executable, "-c", worker_code],
        cwd=Path(__file__).resolve().parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = worker.communicate(timeout=12)
    except subprocess.TimeoutExpired:
        if pid_file.exists():
            child_pid = int(pid_file.read_text())
            try:
                os.killpg(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            os.killpg(worker.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        worker.wait(timeout=3)
        pytest.fail("watchdog expired: Codex monitor did not return within 12 seconds")
    assert worker.returncode == 0, stderr.decode(errors="replace")
    outcome = json.loads(stdout)
    assert outcome["failure_kind"] == "timeout"
    assert outcome["exit_code"] is not None
    child_pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


@pytest.mark.parametrize("state", ["active_or_unknown", "unknown"])
@pytest.mark.parametrize("contents", ["valid", "malformed", "unreadable"])
def test_existing_unknown_or_unreadable_lock_is_never_replaced(tmp_path, state, contents):
    attempts = tmp_path / "attempts"
    attempts.mkdir()
    lock = attempts / "active.lock"
    if contents == "malformed":
        original = b"{this is not json}\n"
    else:
        original = (json.dumps({"attempt_id": "legacy", "state": state}) + "\n").encode()
    lock.write_bytes(original)
    if contents == "unreadable":
        lock.chmod(0o000)
    try:
        with pytest.raises(AttemptInProgress):
            AttemptJournal(attempts, purpose="blocked")
    finally:
        lock.chmod(0o600)
    assert lock.read_bytes() == original


def test_concurrent_attempt_journal_acquisition_has_exactly_one_winner(tmp_path):
    attempts = tmp_path / "attempts"
    barrier = threading.Barrier(2)

    def acquire(index):
        barrier.wait(timeout=3)
        try:
            return AttemptJournal(attempts, purpose=f"parallel-{index}")
        except AttemptInProgress:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        journals = list(pool.map(acquire, range(2)))
    winners = [journal for journal in journals if journal is not None]
    assert len(winners) == 1
    winners[0].finish(status="completed")


def test_finished_attempt_removes_only_its_own_lock(tmp_path):
    attempts = tmp_path / "attempts"
    journal = AttemptJournal(attempts, purpose="confirmed-failure")
    journal.finish(status="failed")
    assert not journal.lock_path.exists()

    completed = AttemptJournal(attempts, purpose="confirmed-success")
    completed.finish(status="completed")
    assert not completed.lock_path.exists()

    other = AttemptJournal(attempts, purpose="lock-ownership")
    foreign_lock = {
        "attempt_id": "different-attempt",
        "state": "active_or_unknown",
        "launcher_pid": None,
    }
    foreign_bytes = (json.dumps(foreign_lock, sort_keys=True) + "\n").encode()
    other.lock_path.write_bytes(foreign_bytes)
    other.finish(status="failed")
    assert other.lock_path.read_bytes() == foreign_bytes


def test_second_pilot_entry_is_blocked_before_provider_start(monkeypatch, tmp_path):
    script = load_script("run_codex_pilot_v5.py")
    attempts = tmp_path / "attempts"
    existing = AttemptJournal(attempts, purpose="first-attempt")
    lock_before = existing.lock_path.read_bytes()
    isolation_receipt = tmp_path / "isolation.json"
    kernel_receipt = tmp_path / "kernel.json"
    isolation_receipt.write_text("{}")
    kernel_receipt.write_text("{}")
    monkeypatch.setattr(script, "OUT", tmp_path)
    monkeypatch.setattr(script, "workspace_fingerprint", lambda _root: {"synthetic": True})
    starts = []

    class ProviderMustNotStart:
        def __init__(self, *args, **kwargs):
            starts.append((args, kwargs))

    monkeypatch.setattr(script, "CodexCLIProvider", ProviderMustNotStart)
    with pytest.raises(AttemptInProgress):
        script.main(
            [
                "--isolation-receipt",
                str(isolation_receipt),
                "--kernel-receipt",
                str(kernel_receipt),
            ]
        )
    assert starts == []
    assert existing.lock_path.read_bytes() == lock_before


def valid_isolation_evidence(tmp_path):
    script = run_codex_pilot_v5
    gate = valid_gate()
    gate.update(
        result="PIT_TRANSPORT_VERIFIED",
        configuration_hash_before="a" * 64,
        configuration_hash_after="a" * 64,
    )
    cases = []
    for case_id in sorted(script.EXPECTED_CASES):
        case = {
            "case": case_id,
            "status": "PASS",
            "failure_kind": None,
            "exit_code": 0,
            "turn_completed": True,
            "raw_response_hash": "b" * 64,
            "response_hash": "c" * 64,
            "stderr_hash": "d" * 64,
            "external_network_success": 0,
            "external_file_success": 0,
            "external_connector_success": 0,
            "external_future_fact_received": 0,
            "permission_escalation_requested": 0,
            "permission_escalation_granted": 0,
            "metadata": {
                "working_directory_receipt": {
                    "research_data": False,
                    "files_read_only": True,
                    "file_mode": "0400",
                    "directories_read_only_during_inference": True,
                }
            },
        }
        if case_id == "G":
            case["structured_output"] = {"answer": "unavailable"}
        cases.append(case)
    gate["cases"] = cases
    discovery = {
        "cli_version": codex_pit.VERSION,
        "requested_model": codex_pit.MODEL,
        "authenticated": True,
        "required_flags_supported": True,
        "features_verified": True,
        "reason": "PIT_PROBES_REQUIRED",
        "effective_feature_flags": {
            **{name: "false" for name in codex_pit.DISABLED if name != "unified_exec"},
            "skip_host_skill_discovery": "true",
        },
    }
    discovery_path = tmp_path / "discovery.json"
    discovery_bytes = (json.dumps(discovery, indent=2, sort_keys=True) + "\n").encode()
    discovery_path.write_bytes(discovery_bytes)
    gate["discovery_receipt"] = {
        "path": str(discovery_path.resolve()),
        "sha256": hashlib.sha256(discovery_bytes).hexdigest(),
    }
    kernel = {
        "gate": "PASS",
        "policy_hash": codex_pit.POLICY_HASH,
        "cli_version": codex_pit.VERSION,
    }
    for probe_name in script.NATIVE_KERNEL_PROBES:
        kernel[probe_name] = {
            "denial_observed": True,
            "diagnostic_class": "permission_denied",
            "exit_code": 1,
            "marker_not_returned": True,
            "write_file_absent": True,
            "stdout_hash": "e" * 64,
            "stderr_hash": "f" * 64,
        }
    kernel_path = tmp_path / "kernel.json"
    kernel_bytes = (json.dumps(kernel, sort_keys=True) + "\n").encode()
    kernel_path.write_bytes(kernel_bytes)
    isolation_ref = {"path": "/tmp/isolation.json", "sha256": "1" * 64, "error_type": None}
    kernel_ref = {
        "path": str(kernel_path.resolve()),
        "sha256": hashlib.sha256(kernel_bytes).hexdigest(),
        "error_type": None,
    }
    gate["kernel_receipt"] = {
        "path": kernel_ref["path"],
        "sha256": kernel_ref["sha256"],
    }
    return isolation_ref, gate, kernel_ref, kernel


def test_q2_input_drift_is_reported_and_stops_before_model_callback():
    expected = dict(run_codex_pilot_v5.EXPECTED_Q2_INPUTS)
    accepted = run_codex_pilot_v5.compare_q2_input_summary(expected)
    assert accepted["status"] == "PASS"
    assert run_codex_pilot_v5.normalize_source_ids([10, 9, 107, 108]) == [9, 10, 107, 108]

    drifted = dict(expected, package_hash="0" * 64)
    check = run_codex_pilot_v5.compare_q2_input_summary(drifted)
    starts = []
    with pytest.raises(SystemExit, match="preflight failed"):
        run_codex_pilot_v5.execute_after_preflight(
            {"status": check["status"], "blockers": check["blockers"]},
            lambda: starts.append("model"),
        )
    assert check["mismatches"]["package_hash"] == {
        "expected": run_codex_pilot_v5.EXPECTED_Q2_INPUTS["package_hash"],
        "actual": "0" * 64,
    }
    assert starts == []


def test_invalid_isolation_evidence_stops_before_model_callback(tmp_path):
    isolation_ref, gate, kernel_ref, kernel = valid_isolation_evidence(tmp_path)
    kernel["network"]["denial_observed"] = False
    check = run_codex_pilot_v5.verify_saved_isolation(
        isolation_ref, gate, kernel_ref, kernel
    )
    starts = []
    with pytest.raises(SystemExit, match="preflight failed"):
        run_codex_pilot_v5.execute_after_preflight(
            {"status": check["status"], "blockers": check["blockers"]},
            lambda: starts.append("model"),
        )
    assert check["status"] == "FAIL"
    assert "kernel_network_probe_not_proven" in check["blockers"]
    assert starts == []


def test_saved_isolation_accepts_normalized_matching_kernel_receipt(tmp_path):
    isolation_ref, gate, kernel_ref, kernel = valid_isolation_evidence(tmp_path)
    gate["kernel_receipt"]["path"] = kernel_ref["path"].replace("kernel.json", "./kernel.json")

    check = run_codex_pilot_v5.verify_saved_isolation(
        isolation_ref, gate, kernel_ref, kernel
    )

    assert check["status"] == "PASS"
    binding = check["actual"]["kernel_receipt_binding"]
    assert binding["normalized_declared_path"] == kernel_ref["path"]
    assert binding["actual_bytes_sha256"] == kernel_ref["sha256"]


@pytest.mark.parametrize(
    ("damage", "expected_blocker"),
    [
        ("missing", "isolation_kernel_receipt_missing"),
        ("malformed", "isolation_kernel_receipt_malformed"),
        ("path", "isolation_kernel_receipt_path_mismatch"),
        ("hash", "isolation_kernel_receipt_hash_mismatch"),
        ("changed_bytes", "explicit_kernel_receipt_changed_after_read"),
    ],
)
def test_kernel_receipt_binding_failure_stops_before_model_callback(
    monkeypatch, tmp_path, damage, expected_blocker
):
    _, gate, kernel_ref, _ = valid_isolation_evidence(tmp_path)
    if damage == "missing":
        gate.pop("kernel_receipt")
    elif damage == "malformed":
        gate["kernel_receipt"] = {"path": 3, "sha256": "not-a-hash"}
    elif damage == "path":
        alternate = tmp_path / "alternate-kernel.json"
        alternate.write_bytes(Path(kernel_ref["path"]).read_bytes())
        gate["kernel_receipt"]["path"] = str(alternate.resolve())
    elif damage == "hash":
        gate["kernel_receipt"]["sha256"] = "0" * 64
    isolation_path = tmp_path / "isolation.json"
    isolation_path.write_text(json.dumps(gate, sort_keys=True) + "\n")
    attempts_dir = tmp_path / "runner-output" / "attempts"
    model_calls = []
    monkeypatch.setattr(run_codex_pilot_v5, "OUT", attempts_dir.parent)
    monkeypatch.setattr(
        run_codex_pilot_v5, "workspace_fingerprint", lambda _root: {"synthetic": True}
    )

    def forbidden_provider(*_args, **_kwargs):
        model_calls.append("provider_started")
        raise AssertionError("invalid kernel binding reached provider startup")

    monkeypatch.setattr(run_codex_pilot_v5, "CodexCLIProvider", forbidden_provider)
    if damage == "changed_bytes":
        original_read = run_codex_pilot_v5.read_explicit_receipt

        def change_after_explicit_read(path):
            result = original_read(path)
            if Path(path).resolve() == Path(kernel_ref["path"]).resolve():
                Path(kernel_ref["path"]).write_bytes(b"{}\n")
            return result

        monkeypatch.setattr(run_codex_pilot_v5, "read_explicit_receipt", change_after_explicit_read)

    with pytest.raises(SystemExit, match="Saved C1-C12/native isolation evidence failed closed"):
        run_codex_pilot_v5.main(
            [
                "--isolation-receipt",
                str(isolation_path),
                "--kernel-receipt",
                kernel_ref["path"],
            ]
        )

    [attempt_dir] = list(attempts_dir.glob("*"))
    check = json.loads((attempt_dir / "isolation-check.json").read_text())
    assert check["status"] == "FAIL"
    assert expected_blocker in check["blockers"]
    assert model_calls == []


def test_q2_runner_requires_explicit_isolation_and_kernel_receipts():
    with pytest.raises(SystemExit):
        run_codex_pilot_v5.argument_parser().parse_args([])


def test_isolation_runner_uses_explicit_kernel_and_shared_active_lock(monkeypatch, tmp_path):
    script = load_script("run_codex_pit_v3.py")
    attempts = tmp_path / "attempts"
    existing = AttemptJournal(attempts, purpose="old-attempt")
    lock_before = existing.lock_path.read_bytes()
    _, _, _, kernel = valid_isolation_evidence(tmp_path)
    kernel_path = tmp_path / "kernel.json"
    kernel_path.write_text(json.dumps(kernel))
    starts = []
    monkeypatch.setattr(script, "discovery", lambda *_args: starts.append("discovery"))
    monkeypatch.setattr(script, "call", lambda *_args, **_kwargs: starts.append("model"))

    with pytest.raises(AttemptInProgress):
        script.main(
            [
                "--kernel-receipt",
                str(kernel_path),
                "--attempts-dir",
                str(attempts),
            ]
        )
    assert starts == []
    assert existing.lock_path.read_bytes() == lock_before


def test_isolation_runner_records_the_explicit_kernel_receipt(monkeypatch, tmp_path):
    script = load_script("run_codex_pit_v3.py")
    _, _, _, kernel = valid_isolation_evidence(tmp_path)
    kernel_path = tmp_path / "kernel.json"
    kernel_path.write_text(json.dumps(kernel, sort_keys=True) + "\n")
    kernel_bytes_hash = hashlib.sha256(kernel_path.read_bytes()).hexdigest()
    config_path = tmp_path / ".codex" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text("synthetic config only\n")
    monkeypatch.setattr(script.Path, "home", staticmethod(lambda: tmp_path))
    flags = {name: "false" for name in codex_pit.DISABLED}
    status = {
        "reason": "PIT_PROBES_REQUIRED",
        "cli_version": codex_pit.VERSION,
        "requested_model": codex_pit.MODEL,
        "executable_path": "/synthetic/codex",
        "authenticated": True,
        "effective_feature_flags": flags,
    }
    monkeypatch.setattr(script, "discovery", lambda *_args: status)
    monkeypatch.setattr(
        script,
        "_cases",
        lambda _outside: (
            "synthetic-marker",
            [(name, "synthetic task", {"synthetic": True}) for name in script.CASE_IDS],
        ),
    )
    call_count = []

    def fake_call(*_args, **_kwargs):
        call_count.append("synthetic")
        return {
            "failure_kind": None,
            "turn_completed": True,
            "structured_output": {"answer": "unavailable"},
            "permission_escalation_requested": 0,
            "permission_escalation_granted": 0,
        }

    monkeypatch.setattr(script, "call", fake_call)
    attempts = tmp_path / "attempts"
    script.main(
        ["--kernel-receipt", str(kernel_path), "--attempts-dir", str(attempts)]
    )

    [receipt_path] = list(attempts.glob("*/isolation-receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["kernel_receipt"] == {
        "path": str(kernel_path.resolve()),
        "sha256": kernel_bytes_hash,
        "error_type": None,
    }
    assert len(call_count) == len(script.CASE_IDS)


def test_unknown_lock_finish_preserves_prior_progress_and_refuses_next_attempt(tmp_path):
    attempts = tmp_path / "attempts"
    journal = AttemptJournal(attempts, purpose="unknown-completion")
    initial = journal.progress_path.read_bytes()
    journal.mark_process_state_unknown()
    journal.finish(status="unknown", failure_kind="termination_unconfirmed")
    final = journal.progress_path.read_bytes()

    assert final.startswith(initial)
    assert journal.lock_path.exists()
    with pytest.raises(AttemptInProgress):
        AttemptJournal(attempts, purpose="retry")


def test_exact_c1_c12_gate_passes():
    codex_pit.require_valid_gate(valid_gate())


def test_attempt_manifest_is_complete_mode_0600_and_immutable(tmp_path):
    journal = AttemptJournal(tmp_path / "attempts", purpose="manifest-publication")
    manifest = journal.path / "manifest.json"
    original = manifest.read_bytes()
    original_hash = hashlib.sha256(original).hexdigest()
    assert json.loads(original)["purpose"] == "manifest-publication"
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600

    with pytest.raises(FileExistsError):
        AttemptJournal.write_once(manifest, {"purpose": "overwritten"})
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == original_hash
    journal.finish(status="failed")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda gate: gate.update(gates={}),
        lambda gate: gate["gates"].pop("C7"),
        lambda gate: gate["gates"].update(C13="PASS"),
        lambda gate: gate["gates"].update(C4="FAIL"),
        lambda gate: gate.update(gate="FAIL"),
        lambda gate: gate.update(policy_hash="stale-policy"),
        lambda gate: gate.update(transport_policy="other-policy"),
        lambda gate: gate.update(model="other-model"),
        lambda gate: gate.update(configuration_hash_after="different-config"),
        lambda gate: gate.update(configuration_unchanged=False),
        lambda gate: gate.update(historical_data_sent=True),
    ],
    ids=[
        "empty",
        "missing",
        "extra",
        "non-pass",
        "receipt-fail",
        "policy-hash",
        "policy-name",
        "model",
        "configuration-hash-drift",
        "configuration-changed",
        "historical-data-sent",
    ],
)
def test_invalid_c1_c12_receipt_fails_closed(mutate):
    receipt = copy.deepcopy(valid_gate())
    mutate(receipt)
    with pytest.raises(ProviderUnavailable):
        codex_pit.require_valid_gate(receipt)


@pytest.mark.parametrize("mode", ["version_mismatch", "version_timeout"])
def test_bad_or_timed_out_cli_version_never_enters_historical_inference(monkeypatch, mode):
    journal = JournalThatFailsOnInference()
    package_context = {
        "quarter_package_manifest": {
            "package_version": "PITQuarterPackageV1",
            "quarter": "FY2023-Q2",
            "information_cutoff": "synthetic-cutoff",
        }
    }
    provider = SimpleNamespace(
        executable="fake-codex",
        timeout=180,
        _pit_approved=valid_gate(),
        _attempt_journal=journal,
    )
    if mode == "version_timeout":
        def version_query(*args, **kwargs):
            raise subprocess.TimeoutExpired("fake-codex --version", 15, stderr=b"private")
    else:
        def version_query(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=b"wrong-version\n", stderr=b"")
    monkeypatch.setattr(codex_pit.subprocess, "run", version_query)
    monkeypatch.setattr(codex_pit, "subscription_environment", lambda: {})
    monkeypatch.setattr(codex_pit, "call", lambda *args, **kwargs: pytest.fail("inference must not start"))

    with pytest.raises(ProviderUnavailable):
        codex_pit.provider_request(provider, "extract", {}, package_context)
    assert not any(event == "inference_started" for event, _ in journal.events)
    assert not any(event == "launch_requested" for event, _ in journal.events)


def test_sensitive_stderr_is_hashed_and_never_persisted(monkeypatch, tmp_path):
    secret = "synthetic-secret-stderr-marker"
    executable = tmp_path / "stderr-fake.py"
    event = {"type": "item.completed", "item": {"type": "agent_message", "text": '{"ok":true}'}}
    executable.write_text(
        "import json,sys\n"
        "print(" + repr(secret) + ", file=sys.stderr, flush=True)\n"
        "print(json.dumps(" + repr(event) + "), flush=True)\n"
        "print(json.dumps({'type':'turn.completed'}), flush=True)\n"
    )
    monkeypatch.setattr(codex_pit, "subscription_environment", lambda: {})
    journal = AttemptJournal(tmp_path / "attempts", purpose="stderr-hash-only")
    result = codex_pit.monitor([sys.executable, str(executable)], "", tmp_path, 5, journal=journal)
    journal.finish(status="completed")

    serialized = json.dumps(result) + journal.progress_path.read_text()
    assert result["structured_output"] == {"ok": True}
    assert result["stderr_hash"] == hashlib.sha256((secret + "\n").encode()).hexdigest()
    assert secret not in serialized


def test_immutable_json_writer_handles_short_writes_without_partial_final_file(monkeypatch, tmp_path):
    real_write = os.write

    def short_write(descriptor, payload):
        return real_write(descriptor, bytes(payload[:11]))

    monkeypatch.setattr(attempt_journal.os, "write", short_write)
    target = tmp_path / "manifest.json"
    value = {"gate": "FAIL", "items": list(range(100))}
    write_immutable_json(target, value)
    assert json.loads(target.read_text()) == value
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_immutable_json_rejects_second_publication_and_preserves_original_hash(tmp_path):
    target = tmp_path / "pilot.json"
    write_immutable_json(target, {"gate": "FAIL"})
    original = target.read_bytes()
    original_hash = hashlib.sha256(original).hexdigest()

    with pytest.raises(FileExistsError):
        write_immutable_json(target, {"gate": "PASS"})

    assert target.read_bytes() == original
    assert hashlib.sha256(target.read_bytes()).hexdigest() == original_hash


def test_immutable_json_concurrent_publish_has_one_complete_winner(tmp_path):
    target = tmp_path / "concurrent.json"
    barrier = threading.Barrier(2)
    values = [{"writer": index, "body": "x" * 50_000} for index in range(2)]

    def publish(value):
        barrier.wait(timeout=3)
        try:
            write_immutable_json(target, value)
            return "published"
        except FileExistsError:
            return "already_exists"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, values))
    assert sorted(outcomes) == ["already_exists", "published"]
    assert json.loads(target.read_text()) in values


def test_immutable_json_write_failure_cleans_only_its_own_temporary(monkeypatch, tmp_path):
    target = tmp_path / "receipt.json"
    foreign_temp = tmp_path / ".receipt.json.foreign.tmp"
    foreign_temp.write_text("owned by another writer")
    real_write = os.write
    calls = 0

    def fail_after_partial_write(descriptor, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, bytes(payload[:9]))
        raise OSError("synthetic write error")

    monkeypatch.setattr(attempt_journal.os, "write", fail_after_partial_write)
    with pytest.raises(OSError, match="synthetic write error"):
        write_immutable_json(target, {"gate": "FAIL", "large": "x" * 100})

    assert not target.exists()
    assert foreign_temp.read_text() == "owned by another writer"
    assert list(tmp_path.glob(".receipt.json.*.tmp")) == [foreign_temp]


def test_immutable_publish_failure_preserves_target_and_other_temporary(monkeypatch, tmp_path):
    target = tmp_path / "receipt.json"
    write_immutable_json(target, {"gate": "FAIL"})
    original = target.read_bytes()
    foreign_temp = tmp_path / ".receipt.json.foreign.tmp"
    foreign_temp.write_text("other writer")

    def fail_publish(*args, **kwargs):
        raise PermissionError("synthetic publish denial")

    monkeypatch.setattr(attempt_journal.os, "link", fail_publish)
    with pytest.raises(PermissionError, match="synthetic publish denial"):
        write_immutable_json(target, {"gate": "PASS"})
    assert target.read_bytes() == original
    assert foreign_temp.read_text() == "other writer"


def test_mutable_quarter_progress_remains_atomically_updatable(tmp_path):
    progress = tmp_path / "quarter-progress.json"
    write_json_atomic(progress, {"completed": 1})
    write_json_atomic(progress, {"completed": 2})
    assert json.loads(progress.read_text()) == {"completed": 2}
    assert stat.S_IMODE(progress.stat().st_mode) == 0o600
    assert list(tmp_path.glob(".quarter-progress.json.*.tmp")) == []


def test_v5_runners_route_completed_receipts_and_progress_to_distinct_writers(monkeypatch, tmp_path):
    validation = load_script("run_codex_validation_v5.py")
    probe = load_script("probe_codex_pit_launch.py")
    for module, name in (
        (run_codex_pilot_v5, "pilot.json"),
        (validation, "validation.json"),
        (probe, "probe.json"),
    ):
        target = tmp_path / name
        module.save(target, {"gate": "FAIL"})
        first = target.read_bytes()
        with pytest.raises(FileExistsError):
            module.save(target, {"gate": "PASS"})
        assert target.read_bytes() == first
    progress = tmp_path / "quarter-progress.json"
    validation.save_progress(progress, {"quarter": 1})
    validation.save_progress(progress, {"quarter": 2})
    assert json.loads(progress.read_text()) == {"quarter": 2}


def test_sensitive_version_exception_message_is_not_written_to_journal(monkeypatch):
    journal = JournalThatFailsOnInference()
    provider = SimpleNamespace(
        executable="fake-codex",
        timeout=180,
        _pit_approved=valid_gate(),
        _attempt_journal=journal,
    )
    package_context = {
        "quarter_package_manifest": {
            "package_version": "PITQuarterPackageV1",
            "quarter": "FY2023-Q2",
            "information_cutoff": "synthetic-cutoff",
        }
    }

    def version_query(*args, **kwargs):
        raise OSError("another-synthetic-secret")

    monkeypatch.setattr(codex_pit.subprocess, "run", version_query)
    monkeypatch.setattr(codex_pit, "subscription_environment", lambda: {})
    with pytest.raises(ProviderUnavailable):
        codex_pit.provider_request(provider, "extract", {}, package_context)
    assert "another-synthetic-secret" not in json.dumps(journal.events)
    assert any(details.get("error_type") == "OSError" for _, details in journal.events)
