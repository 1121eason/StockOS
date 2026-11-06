"""Standalone trusted AGY hook, copied into a fresh non-research workspace.

No supplied tool arguments are executed or retained. The only admitted tool is
AGY's structured-answer emitter. Configuration drift blocks model invocation.
"""

import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def main():
    event = sys.argv[1] if len(sys.argv) == 2 else "invalid"
    config = json.loads(Path(__file__).with_name("guard.json").read_text())
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict):
        raise ValueError("Invalid hook payload")
    call = payload.get("toolCall", {})
    call = call if isinstance(call, dict) else {}
    name = call.get("name")
    record = {
        "event": event,
        "nonce": config["nonce"],
        "at": datetime.now(UTC).isoformat(),
        "conversation_id": payload.get("conversationId"),
        "workspaces": payload.get("workspacePaths"),
        "model_name": payload.get("modelName"),
        "tool_name": name,
        "args_sha256": digest(canonical(call.get("args", {}))),
        "step_index": payload.get("stepIdx"),
        "invocation_number": payload.get("invocationNum"),
    }
    drift = []
    for path, expected in config["protected_hashes"].items():
        item = Path(path)
        if item.is_symlink() or not item.is_file() or digest(item.read_bytes()) != expected:
            drift.append(path)
    record["configuration_matches"] = not drift
    # Only path hashes are retained on drift, not arbitrary file contents.
    if drift:
        record["drift_path_hashes"] = [digest(path.encode()) for path in drift]
    if event == "pre":
        record["decision"] = "allow" if name == "finish" and not drift else "deny"
        output = {
            "decision": record["decision"],
            "reason": "StockOS supplied-evidence-only boundary; external tools are prohibited.",
        }
    elif event == "invocation":
        number = payload.get("invocationNum")
        stop = (
            bool(drift)
            or type(number) is not int
            or number < 0
            or number >= config["max_model_invocations"]
        )
        record["blocked"] = stop
        output = (
            {
                "terminationBehavior": "terminate",
                "injectSteps": [
                    {
                        "errorMessage": {
                            "userMessage": "StockOS configuration or invocation boundary failed."
                        }
                    }
                ],
            }
            if stop
            else {}
        )
    elif event == "post":
        error = payload.get("error")
        record["error_present"] = bool(error)
        record["error_sha256"] = digest(str(error).encode()) if error else None
        message = str(error).lower()
        record["denial_observed"] = (
            bool(error)
            and not any(
                value in message for value in ("not denied", "not blocked", "subsystem unavailable")
            )
            and bool(
                re.search(
                    r"permission[ _-](?:was )?denied|access (?:was )?denied|(?:blocked|denied) by (?:the |a )?(?:pre.?tool.?use|hook|permission)|tool (?:call |execution |use )?(?:was )?(?:denied|blocked)",
                    message,
                )
            )
        )
        output = {}
    elif event == "stop":
        record["fully_idle"] = payload.get("fullyIdle")
        record["termination_reason"] = payload.get("terminationReason")
        output = {"decision": "stop"}
    elif event in ("session", "postinvocation"):
        output = {}
    else:
        raise ValueError("Unknown hook event")
    audit = Path(config["audit_path"])
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW
    fd = os.open(audit, flags, 0o600)
    with os.fdopen(fd, "ab") as stream:
        stream.write(canonical(record) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(output), flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        # An unreadable policy/audit trail must never turn into an allow decision.
        if len(sys.argv) == 2 and sys.argv[1] == "pre":
            print(
                json.dumps({"decision": "deny", "reason": "StockOS hook failed closed."}),
                flush=True,
            )
        else:
            print(json.dumps({"terminationBehavior": "terminate"}), flush=True)
        raise SystemExit(2) from None
