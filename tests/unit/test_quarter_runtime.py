import json
import sys

import pytest

from valuation_engine.ai import quarter_runtime as runtime


def setup(tmp_path, monkeypatch, *, tool=False, stall=False, close_before_exit=False):
    monkeypatch.setattr(runtime, "native_process_rows", lambda directory, name: [])
    exe = tmp_path / "fake-cli"
    program = "import json,sys,time\nsys.stdin.read()\n"
    if tool:
        program += "print(json.dumps({'type':'item.started','item':{'type':'command_execution'}}),flush=True)\ntime.sleep(10)\n"
    elif stall:
        program += "time.sleep(10)\n"
    else:
        program += "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{\"answer\":\"unavailable\"}'}}))\nprint(json.dumps({'type':'turn.completed'}))\n"
    if close_before_exit:
        program += "sys.stdout.flush();sys.stderr.flush()\nimport os\nos.close(1);os.close(2)\ntime.sleep(0.2)\n"
    exe.write_text("#!" + sys.executable + "\n" + program)
    exe.chmod(0o700)
    monkeypatch.setattr(runtime, "CLI_SHA", runtime.sha(exe.read_bytes()))
    state = tmp_path / "shared"
    approval = {
        "contract_hash": runtime.CONTRACT_HASH,
        "decision": "APPROVED_BY_USER",
        "user_instruction": "Synthetic test only",
        "shared_state_root": str(state.resolve()),
    }
    return runtime.Execution(state, tmp_path / "output", approval, exe)


def request():
    return {
        "system": "Synthetic",
        "task": "Return unavailable",
        "untrusted_data": {},
        "response_schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    }


def test_no_bound_user_scope_decision(tmp_path):
    with pytest.raises(ValueError):
        runtime.Execution(tmp_path, tmp_path / "out", {}, tmp_path / "absent")


def test_raw_request_response_and_shared_budget_survive_new_output(tmp_path, monkeypatch):
    execution = setup(tmp_path, monkeypatch)
    with execution:
        result = execution.request("diagnostic", "synthetic", request())
        assert result["structured_output"] == {"answer": "unavailable"}
        assert result["response_model"] is None
        assert (execution.output / "call-0001/stdout.jsonl").read_text()
    assert not execution.lock.exists()
    assert json.loads((execution.root / "attempt-0001.json").read_text())["status"] == "COMPLETED"


@pytest.mark.parametrize("kind", ["tool", "timeout"])
def test_failure_consumes_attempt_and_refuses_retry(tmp_path, monkeypatch, kind):
    execution = setup(tmp_path, monkeypatch, tool=kind == "tool", stall=kind == "timeout")
    with execution:
        with pytest.raises(RuntimeError):
            execution.request("diagnostic", "synthetic", request(), timeout=0.1)
        with pytest.raises(ValueError, match="retry refused"):
            execution.request("diagnostic", "synthetic", request())
        assert execution.calls[0]["group_absent"] is True
    assert json.loads((execution.root / "attempt-0001.json").read_text())["status"] == "FAILED"


def test_existing_global_lock_is_never_deleted(tmp_path, monkeypatch):
    execution = setup(tmp_path, monkeypatch)
    execution.root.mkdir()
    execution.lock.write_text("another owner")
    with pytest.raises(FileExistsError):
        with execution:
            pass
    assert execution.lock.read_text() == "another owner"


def test_output_cannot_be_reused(tmp_path, monkeypatch):
    execution = setup(tmp_path, monkeypatch)
    with execution:
        pass
    with pytest.raises(FileExistsError):
        with execution:
            pass


def test_pending_and_failed_history_cannot_reset_with_new_output(tmp_path, monkeypatch):
    execution = setup(tmp_path, monkeypatch)
    execution.root.mkdir()
    (execution.root / "attempt-0001.json").write_text(
        json.dumps({"contract_hash": runtime.CONTRACT_HASH, "status": "PENDING"})
    )
    with execution:
        with pytest.raises(ValueError, match="pending or failed"):
            execution.request("diagnostic", "synthetic", request())


def test_binary_drift_is_rejected_before_reserving(tmp_path, monkeypatch):
    execution = setup(tmp_path, monkeypatch)
    execution.exe.write_text("Changed CLI")
    with execution:
        with pytest.raises(ValueError, match="binary changed"):
            execution.request("diagnostic", "synthetic", request())
        assert not list(execution.root.glob("attempt-*.json"))


def test_refused_cleanup_retains_unknown_lock(tmp_path, monkeypatch):
    execution = setup(tmp_path, monkeypatch)
    real_kill = runtime.os.killpg

    def refuse_observation(pid, sig):
        if sig == 0:
            raise PermissionError("Synthetic unknown group state")
        return real_kill(pid, sig)

    monkeypatch.setattr(runtime.os, "killpg", refuse_observation)
    with execution:
        with pytest.raises(RuntimeError):
            execution.request("diagnostic", "synthetic", request())
    assert execution.lock.exists()
    assert json.loads((execution.root / "attempt-0001.json").read_text())["cleanup"] == "UNKNOWN"


def test_diagnostic_cap_cannot_reset(tmp_path, monkeypatch):
    execution = setup(tmp_path, monkeypatch)
    execution.root.mkdir()
    for index in range(1, 8):
        (execution.root / f"attempt-{index:04d}.json").write_text(
            json.dumps(
                {
                    "contract_hash": runtime.CONTRACT_HASH,
                    "phase": "diagnostic",
                    "status": "COMPLETED",
                    "cleanup": "CLEAN",
                }
            )
        )
    with execution:
        with pytest.raises(ValueError, match="cap reached"):
            execution.request("diagnostic", "synthetic", request())


def test_research_is_not_enabled_by_scope_approval_alone(tmp_path, monkeypatch):
    execution = setup(tmp_path, monkeypatch)
    with execution:
        with pytest.raises(ValueError, match="isolation and source"):
            execution.request("research", "extract", request(), method="B")


def test_descendant_tracking_keeps_reparented_known_children():
    assert runtime.descendant_ids([(1, 0), (10, 1), (11, 10), (12, 11), (99, 1)], 10) == {11, 12}
    assert runtime.descendant_ids([(1, 0), (11, 1)], 10, {11, 12}) == {11, 12}


def test_closed_lease_and_excessive_timeout_cannot_start_a_request(tmp_path, monkeypatch):
    execution = setup(tmp_path, monkeypatch)
    with execution:
        with pytest.raises(ValueError, match="timeout"):
            execution.request("diagnostic", "synthetic", request(), timeout=121)
    with pytest.raises(ValueError, match="lease required"):
        execution.request("diagnostic", "synthetic", request())


def test_successful_turn_can_finish_cleanup_without_being_killed(tmp_path, monkeypatch):
    execution = setup(tmp_path, monkeypatch, close_before_exit=True)
    with execution:
        execution.request("diagnostic", "synthetic", request())
        assert execution.calls[0]["exit_code"] == 0
        assert execution.calls[0]["runner_signals"] == []
