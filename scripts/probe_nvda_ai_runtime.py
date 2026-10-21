#!/usr/bin/env python3
"""Non-model sandbox and owned-process probes; never certifies provider readiness."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from valuation_engine.ai.cli_provider import subscription_environment
from valuation_engine.ai.codex_pit import CONFIG, overrides
from valuation_engine.ai.native_preflight import classify_command_probe, sha


def reap_owned_probe(process, lifecycle, save):
    """Exactly one kill on the owned group; persist unknown cleanup on any error."""
    try:
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            lifecycle["timeout_observed"] = True
    finally:
        try:
            if process.poll() is None:
                lifecycle["termination_requested"] = True
                save()
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            lifecycle["reaped"] = True
            lifecycle["exit_code"] = process.returncode
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                lifecycle["group_absent"] = True
            lifecycle["cleanup_status"] = "CLEAN" if lifecycle["group_absent"] else "UNKNOWN"
            if not lifecycle["group_absent"]:
                raise RuntimeError("Owned group remains; further probes stopped")
        except BaseException as error:
            lifecycle["cleanup_status"] = "UNKNOWN"
            lifecycle["error_type"] = type(error).__name__
            raise
        finally:
            save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    receipt: dict = {
        "probe_version": "NVDANonModelNativeProbeV1",
        "probe_script_sha256": sha(Path(__file__).read_bytes()),
        "executable_sha256": sha(Path(args.executable).resolve(strict=True).read_bytes()),
        "started_at": datetime.now(UTC).isoformat(),
        "configuration": CONFIG,
        "model_calls": 0,
        "formal_db_writes": 0,
        "provider_runtime_verified": False,
        "note": "Named-profile command probe only; not a model execution, C1-C12 certificate, or global-process classification approval.",
    }

    def save():
        (args.output_dir / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    def execute(argv, cwd):
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=subscription_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=25)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=5)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
            raise
        group_absent = False
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            group_absent = True
        result = {
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "timeout": timed_out,
            "pid": process.pid,
            "group_absent": group_absent,
        }
        receipt.setdefault("commands", []).append(result)
        save()
        if not group_absent:
            raise RuntimeError("Owned command group remains; further probes stopped")
        return result

    with tempfile.TemporaryDirectory(prefix="nvda-native-", dir=args.output_dir.resolve()) as temp:
        root = Path(temp)
        outside = root / "outside-canary.txt"
        outside.write_bytes(os.urandom(64))
        cwd = root / "workspace"
        cwd.mkdir()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(5)
            port = str(listener.getsockname()[1])
            cases = {
                "outside_read": ["/bin/dd", "if=" + str(outside), "of=/dev/null", "count=1"],
                "workspace_write": ["/bin/sh", "-c", "printf synthetic > probe-write.txt"],
                "network_connect": ["/usr/bin/nc", "-z", "-v", "-G", "2", "127.0.0.1", port],
            }
            receipt["cases"] = {}
            for name, command in cases.items():
                control = execute(command, cwd)
                (cwd / "probe-write.txt").unlink(missing_ok=True)
                argv = [
                    args.executable,
                    *overrides(),
                    "sandbox",
                    "-P",
                    "qve_pit",
                    "-C",
                    str(cwd),
                    *command,
                ]
                restricted = execute(argv, cwd)
                receipt["cases"][name] = {
                    "command": command,
                    "control": control,
                    "restricted": restricted,
                    "result": classify_command_probe(name, control, restricted),
                }
                if control["exit_code"] != 0:
                    raise RuntimeError("Native probe control failed; further probes stopped")

        # The only killed process is this probe's own newly-created process group.
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            env=subscription_environment(),
            cwd=cwd,
            start_new_session=True,
        )
        group = os.getpgid(process.pid)
        lifecycle = {
            "pid": process.pid,
            "pgid": group,
            "ownership": "CREATED_BY_THIS_PROBE",
            "timeout_observed": False,
            "reaped": False,
            "group_absent": False,
            "cleanup_status": "PENDING",
            "termination_requested": False,
        }
        receipt["owned_process_lifecycle"] = lifecycle
        save()
        reap_owned_probe(process, lifecycle, save)
    passed = len(receipt["cases"]) == 3 and all(
        c["result"] == "DENIED_WITH_SUCCESSFUL_CONTROL" for c in receipt["cases"].values()
    )
    receipt["named_profile_isolation"] = "PASS_COMMAND_PROBE_ONLY" if passed else "UNVERIFIED"
    receipt["completed_at"] = datetime.now(UTC).isoformat()
    save()
    print(
        json.dumps(
            {
                k: receipt[k]
                for k in (
                    "named_profile_isolation",
                    "owned_process_lifecycle",
                    "model_calls",
                    "provider_runtime_verified",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
