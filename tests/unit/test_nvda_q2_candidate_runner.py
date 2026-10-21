import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from valuation_engine.ai.quarter_runtime import CLI_SHA, CONTRACT_HASH


def script(name):
    path = Path(__file__).resolve().parents[2] / "scripts" / name
    spec = importlib.util.spec_from_file_location("test_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def kernel():
    markers = {
        "outside_read": "dd: outside-canary.txt: Operation not permitted",
        "workspace_write": "/bin/sh: probe-write.txt: Operation not permitted",
        "network_connect": "nc: 127.0.0.1: Operation not permitted",
    }
    return {
        "executable_sha256": CLI_SHA,
        "named_profile_isolation": "PASS_COMMAND_PROBE_ONLY",
        "owned_process_lifecycle": {"cleanup_status": "CLEAN"},
        "cases": {
            name: {
                "control": {"exit_code": 0, "timeout": False, "group_absent": True},
                "restricted": {
                    "exit_code": 1,
                    "timeout": False,
                    "group_absent": True,
                    "stderr": text,
                },
            }
            for name, text in markers.items()
        },
    }


@pytest.mark.parametrize(
    "fault", ["binary", "missing_control", "failed_control", "startup_failure", "cleanup_unknown"]
)
def test_kernel_claim_alone_cannot_unlock_candidate(tmp_path, fault):
    module = script("run_nvda_q2_candidate.py")
    receipt = copy.deepcopy(kernel())
    if fault == "binary":
        receipt["executable_sha256"] = "0" * 64
    elif fault == "missing_control":
        receipt["cases"].pop("outside_read")
    elif fault == "failed_control":
        receipt["cases"]["outside_read"]["control"]["exit_code"] = 1
    elif fault == "startup_failure":
        receipt["cases"]["outside_read"]["restricted"]["stderr"] = (
            "sandbox-exec: execvp() failed: Operation not permitted"
        )
    else:
        receipt["owned_process_lifecycle"]["cleanup_status"] = "UNKNOWN"
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        module.validate_kernel(path)


def test_isolation_receipt_requires_exact_clean_shared_attempt_ledger(tmp_path):
    module = script("run_nvda_q2_candidate.py")
    receipt = tmp_path / "isolation.json"
    receipt.write_text(
        json.dumps({"contract_hash": CONTRACT_HASH, "status": "PASS", "diagnostic_attempts": 7})
    )
    with pytest.raises(ValueError):
        module.require_isolation(receipt, tmp_path)
    for i in range(7):
        (tmp_path / f"attempt-{i + 1:04d}.json").write_text(
            json.dumps({"phase": "diagnostic", "status": "COMPLETED", "cleanup": "CLEAN"})
        )
    with pytest.raises(ValueError):
        module.require_isolation(receipt, tmp_path)
    (tmp_path / "attempt-0003.json").write_text(
        json.dumps({"phase": "diagnostic", "status": "COMPLETED", "cleanup": "UNKNOWN"})
    )
    with pytest.raises(ValueError):
        module.require_isolation(receipt, tmp_path)


def test_new_controlled_entry_refuses_unbound_provider_before_database_access(tmp_path):
    runner = script("run_fsi_s2_experiment.py")
    untouched = tmp_path / "must-not-exist.db"
    with pytest.raises(ValueError, match="Bound, active"):
        runner.run_controlled_method(
            "method_b", {}, SimpleNamespace(execution=object()), {}, untouched, source_contents={}
        )
    assert not untouched.exists()


def test_complete_synthetic_driver_binds_all_seven_raw_responses(tmp_path, monkeypatch):
    from valuation_engine.ai import quarter_runtime as runtime
    from valuation_engine.ai.codex_pit import DISABLED
    from valuation_engine.ai.native_preflight import sha

    module = script("run_nvda_q2_candidate.py")
    fake = tmp_path / "synthetic-cli"
    fake.write_text(
        "#!"
        + sys.executable
        + '\nimport sys,json\nsys.stdin.read()\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"{\\"answer\\":\\"unavailable\\"}"}}))\nprint(json.dumps({"type":"turn.completed"}))\n'
    )
    fake.chmod(0o700)
    monkeypatch.setattr(runtime, "CLI_SHA", sha(fake.read_bytes()))
    monkeypatch.setattr(module, "CLI_SHA", sha(fake.read_bytes()))
    monkeypatch.setattr(runtime, "native_process_rows", lambda directory, name: [])
    monkeypatch.setattr(
        module,
        "inspect_cli",
        lambda executable: {
            "authenticated": True,
            "features_verified": True,
            "required_flags_supported": True,
            "cli_version": runtime.CLI_VERSION,
            "effective_feature_flags": {name: "false" for name in DISABLED},
        },
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    root, out = tmp_path / "state", tmp_path / "output"
    approval = tmp_path / "synthetic-test-approval.json"
    approval.write_text(
        json.dumps(
            {
                "contract_hash": CONTRACT_HASH,
                "decision": "APPROVED_BY_USER",
                "user_instruction": "SYNTHETIC TEST ONLY - NO HUMAN APPROVAL OR MODEL CALL",
                "shared_state_root": str(root),
            }
        )
    )
    receipt = kernel()
    receipt["executable_sha256"] = sha(fake.read_bytes())
    for case in receipt["cases"].values():
        case["result"] = "DENIED_WITH_SUCCESSFUL_CONTROL"
    kernel_file = tmp_path / "synthetic-kernel.json"
    kernel_file.write_text(json.dumps(receipt))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_nvda_q2_candidate.py",
            "--phase",
            "diagnostic",
            "--approval",
            str(approval),
            "--state-root",
            str(root),
            "--output-dir",
            str(out),
            "--executable",
            str(fake),
            "--kernel-receipt",
            str(kernel_file),
        ],
    )
    module.main()
    assert module.require_isolation(out / "isolation.json", root)["status"] == "PASS"
    assert len(list(root.glob("attempt-*.json"))) == 7
    (out / "call-0001/stdout.jsonl").write_text("tampered")
    with pytest.raises(ValueError, match="raw stream changed"):
        module.require_isolation(out / "isolation.json", root)
