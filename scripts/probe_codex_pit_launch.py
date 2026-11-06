"""Run one synthetic, non-historical Codex PIT lifecycle probe."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from valuation_engine.ai.attempt_journal import (
    AttemptJournal,
    workspace_fingerprint,
    write_immutable_json,
)
from valuation_engine.ai.cli_provider import CodexCLIProvider
from valuation_engine.ai.codex_pit import MODEL, POLICY, POLICY_HASH, VERSION, call
from valuation_engine.db.store import digest

OUT = Path("data/m41/codex")


def save(path: Path, value: dict) -> None:
    write_immutable_json(path, value)


def _diagnostic_sidecar(attempt_id: str, result: dict | None, failure_kind: str | None) -> dict:
    result = result or {}
    return {
        "schema": "CodexPITProbeDiagnosticsV1",
        "attempt_id": attempt_id,
        "failure_kind": failure_kind,
        "process_state": result.get("process_state", "not_started"),
        "launch_requested_at": result.get("launch_requested_at"),
        "started_at": result.get("started_at"),
        "completed_at": result.get("completed_at"),
        "observed_exit_code": result.get("observed_exit_code", result.get("exit_code")),
        "launch_error_type": result.get("launch_error_type"),
        "stdout_hash": result.get("raw_response_hash"),
        "stderr_hash": result.get("stderr_hash"),
        "events": result.get("events", []),
        "events_seen": result.get("events_seen", 0),
        "events_truncated": result.get("events_truncated", False),
        "first_failure": result.get("first_failure"),
        "runner_termination_requests": result.get("runner_termination_requests", []),
        "wait_results": result.get("wait_results", []),
    }


def _load_launch_intent(path: str | Path | None) -> dict | None:
    if path is None:
        return None
    intent_path = Path(path)
    if intent_path.is_symlink():
        raise ValueError("launch intent path must not be a symlink")
    resolved = intent_path.resolve(strict=True)
    intent_bytes = resolved.read_bytes()
    intent = json.loads(intent_bytes)
    if (
        not isinstance(intent, dict)
        or intent.get("schema") != "CodexPITProbeLaunchIntentV1"
        or intent.get("historical_input") is not False
    ):
        raise ValueError("launch intent is missing or invalid")
    return {
        "path": str(resolved),
        "sha256": hashlib.sha256(intent_bytes).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-intent")
    arguments = parser.parse_args([] if argv is None else argv)
    launch_intent = _load_launch_intent(arguments.launch_intent)
    journal = AttemptJournal(
        OUT / "attempts",
        purpose="codex_pit_synthetic_launch_probe",
        manifest={
            "git": workspace_fingerprint(Path.cwd()),
            "provider": "codex_cli",
            "requested_model": MODEL,
            "cli_version_expected": VERSION,
            "transport_policy": POLICY,
            "transport_policy_hash": POLICY_HASH,
            "historical_input": False,
            "launch_intent": launch_intent,
        },
    )
    outcome = "failed"
    exit_status = 1
    error_type = None
    receipt = None
    result = None
    failure_kind = None
    phase = "runner_start"
    try:
        journal.emit("runner_started", stage="synthetic_probe", status="started", pid=os.getpid())
        provider = CodexCLIProvider(MODEL, timeout=180)
        phase = "provider_discovery"
        capability = provider.check()
        save(journal.path / "provider-check.json", capability)
        passed = capability.get("reason") == "PIT_PROBES_REQUIRED"
        journal.emit(
            "provider_checked",
            stage="discovery",
            status="passed" if passed else "failed",
            reason=capability.get("reason"),
            cli_version=capability.get("cli_version"),
        )
        if not passed:
            failure_kind = capability.get("reason") or "provider_discovery_failed"
            receipt = {
                "gate": "FAIL",
                "failure_kind": failure_kind,
                "historical_input": False,
                "attempt_id": journal.attempt_id,
                "launch_intent": launch_intent,
            }
        else:
            phase = "inference"
            exact = {
                "system": "Return only the required JSON object. This is a synthetic connectivity probe.",
                "task": "Return {\"ok\": true}.",
                "untrusted_data": {"probe": "synthetic", "historical_data": False},
                "response_schema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean", "const": True}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
            }
            result = call(
                exact,
                provider.executable,
                timeout=180,
                stage="synthetic",
                journal=journal,
            )
            ok = (
                result.get("failure_kind") is None
                and result.get("structured_output") == {"ok": True}
                and result.get("exit_code") == 0
            )
            failure_kind = result.get("failure_kind")
            receipt = {
                "gate": "PASS" if ok else "FAIL",
                "historical_input": False,
                "attempt_id": journal.attempt_id,
                "requested_model": MODEL,
                "cli_version": VERSION,
                "policy_hash": POLICY_HASH,
                "launch_intent": launch_intent,
                "failure_kind": result.get("failure_kind"),
                "launch_requested_at": result.get("launch_requested_at"),
                "started_at": result.get("started_at"),
                "completed_at": result.get("completed_at"),
                "exit_code": result.get("exit_code"),
                "response_hash": digest(result),
                "stdout_hash": result.get("raw_response_hash"),
                "stderr_hash": result.get("stderr_hash"),
                "launch_error_type": result.get("launch_error_type"),
            }
        diagnostic_path = journal.path / "diagnostics.json"
        phase = "diagnostic_write"
        save(
            diagnostic_path,
            _diagnostic_sidecar(journal.attempt_id, result, failure_kind),
        )
        diagnostic_bytes = diagnostic_path.read_bytes()
        receipt["diagnostic_receipt"] = {
            "path": str(diagnostic_path.relative_to(OUT)),
            "sha256": hashlib.sha256(diagnostic_bytes).hexdigest(),
        }
        outcome = "completed" if receipt["gate"] == "PASS" else "failed"
        exit_status = 0 if receipt["gate"] == "PASS" else 1
        phase = "lifecycle_completion"
        journal.emit(
            "stage_completed",
            stage="synthetic_probe",
            status=receipt["gate"].lower(),
            failure_kind=receipt.get("failure_kind"),
        )
        phase = "probe_receipt_write"
        save(journal.path / "probe.json", receipt)
        phase = "complete"
        print(json.dumps(receipt, sort_keys=True))
    except Exception as exc:
        error_type = type(exc).__name__
        outcome = "failed"
        exit_status = 1
        failure_kind = (
            "diagnostic_receipt_write_failure"
            if phase == "diagnostic_write"
            else "probe_receipt_write_failure"
            if phase == "probe_receipt_write"
            else "probe_execution_failure"
        )
        try:
            journal.emit(
                "probe_execution_failed",
                stage="synthetic_probe",
                status="failed",
                failure_kind=failure_kind,
                error_type=error_type,
                phase=phase,
            )
        except Exception:
            pass
    finally:
        journal.finish(
            status="unknown" if journal.process_state_unknown else outcome,
            failure_kind="termination_unconfirmed" if journal.process_state_unknown else None,
            error_type=error_type,
        )
    return exit_status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
