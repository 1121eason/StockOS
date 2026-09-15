"""Experimental V2 boundary; no database imports or official snapshot writes."""

import base64
import fcntl
import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from valuation_engine.ai.cli_provider import antigravity_agent_definition, subscription_environment
from valuation_engine.ai.provider import ProviderUnavailable
from valuation_engine.db.store import digest

POLICY = "AntigravityTransportPolicyV2-PITQuarantine"
DENIES = [
    f"{n}(*)"
    for n in ("read_file", "write_file", "read_url", "execute_url", "command", "unsandboxed", "mcp")
]
CONFIG = {
    "permissions": {"deny": DENIES, "allow": [], "ask": []},
    "toolPermission": "strict",
    "enableTerminalSandbox": True,
    "allowNonWorkspaceAccess": False,
    "useG1Credits": False,
}
SETTINGS = Path.home() / ".gemini/antigravity-cli/settings.json"
AGENT = "qve-pit-analyst"
POLICY_HASH = digest([POLICY, CONFIG, antigravity_agent_definition()])


def atomic(path, data, mode=0o600):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".qve-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def restore(settings, journal):
    receipt = json.loads(journal.read_text())
    if receipt["original_exists"]:
        atomic(settings, base64.b64decode(receipt["original_bytes"]), receipt["original_mode"])
    else:
        settings.unlink(missing_ok=True)
    restored = settings.read_bytes() if settings.exists() else b""
    assert hashlib.sha256(restored).hexdigest() == receipt["original_hash"]
    assert settings.exists() == receipt["original_exists"]
    journal.unlink()


def recover_settings(settings=SETTINGS):
    """Repair an interrupted experiment; never restore over an active owner."""
    settings = Path(settings)
    journal = settings.with_name("qve-quarantine-recovery.json")
    if not journal.exists():
        return False
    record = json.loads(journal.read_text())
    try:
        os.kill(record["owner_pid"], 0)
    except ProcessLookupError:
        restore(settings, journal)
        return True
    raise ProviderUnavailable("Quarantine owner is still alive; recovery refused")


def deny_settings(original):
    if not isinstance(original, dict):
        raise ProviderUnavailable("Settings must be a JSON object")

    # Configuration only. Never back up a credential-bearing settings document.
    def inspect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if re.search(r"token|password|secret|api.?key|oauth|credential", key, re.I):
                    raise ProviderUnavailable("Credential-like setting key; backup refused")
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    inspect(original)
    return {**original, **CONFIG}


@contextmanager
def temporary_policy(settings=SETTINGS):
    settings = Path(settings)
    settings.parent.mkdir(parents=True, exist_ok=True)
    if settings.is_symlink():
        raise ProviderUnavailable("Symlink settings refused")
    lockpath = settings.with_name("qve-quarantine.lock")
    with lockpath.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recover_settings(settings)
        original_exists = settings.exists()
        original = settings.read_bytes() if original_exists else b""
        config = deny_settings(json.loads(original) if original else {})
        record = {
            "original_exists": original_exists,
            "original_bytes": base64.b64encode(original).decode(),
            "original_hash": hashlib.sha256(original).hexdigest(),
            "original_mode": settings.stat().st_mode & 0o777 if original_exists else 0o600,
            "owner_pid": os.getpid(),
        }
        journal = settings.with_name("qve-quarantine-recovery.json")
        atomic(journal, json.dumps(record).encode())
        receipt = {
            "original_exists": original_exists,
            "original_hash": record["original_hash"],
            "temporary_policy_hash": digest(config),
            "restored": False,
        }
        old_handlers = {}

        def interrupted(signum, frame):
            raise InterruptedError(f"Signal {signum}")

        try:
            for signum in (signal.SIGTERM, signal.SIGINT):
                old_handlers[signum] = signal.signal(signum, interrupted)
            atomic(settings, json.dumps(config).encode())
            receipt["settings_readback_matches"] = json.loads(settings.read_text()) == config
            yield receipt
        finally:
            try:
                restore(settings, journal)
                receipt["restored"] = True
            finally:
                for signum, handler in old_handlers.items():
                    signal.signal(signum, handler)


def verify_workspace(cwd):
    expected = {".agents/agents/qve-pit-analyst/agent.md"}
    found = set()
    for p in Path(cwd).rglob("*"):
        if p.is_symlink():
            raise ProviderUnavailable("Workspace symlink refused")
        if p.is_file():
            found.add(str(p.relative_to(cwd)))
    if found != expected or (Path(cwd) / ".git").exists():
        raise ProviderUnavailable("Unexpected file in quarantine workspace")
    return {"verified": True, "regular_files": sorted(found), "research_files_present": False}


def tool_nodes(value):
    if isinstance(value, dict):
        if value.get("step_type") == "tool":
            yield value
        for child in value.values():
            yield from tool_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from tool_nodes(child)


def kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        if process.poll() is None:
            raise


def tool_audit(node):
    info = node.get("tool_info") or {}
    name = node.get("tool_name") or info.get("name") or "unknown"
    output = info.get("output")
    error = info.get("error")
    denied = bool(
        error and re.search(r"denied|permission|not allowed|blocked", json.dumps(error), re.I)
    )
    # An ACTIVE event without a result is not proof the external operation never ran.
    external = name != "finish"
    received = False if not external or denied else (True if output else None)
    category = (
        "external_command_success_count"
        if name in {"run_command", "command_status", "send_command_input", "notebook_execution"}
        else "external_file_read_success_count"
        if name in {"view_file", "grep_search", "find_by_name", "list_dir", "read_resource"}
        else "subagent_success_count"
        if "subagent" in name
        else "mcp_success_count"
        if "mcp" in name
        else "external_network_success_count"
    )
    counters: dict[str, int | None] = {
        k: 0
        for k in (
            "external_network_success_count",
            "external_file_read_success_count",
            "external_command_success_count",
            "subagent_success_count",
            "mcp_success_count",
        )
    }
    if external:
        counters[category] = 1 if received is True else (0 if received is False else None)
    return {
        "tool_name": name,
        "state": node.get("state"),
        "attempted_tool_call": True,
        "blocked_by_permission": denied if error else None,
        "external_data_received": received,
        "output_hash": digest(output) if output else None,
        "tool_execution_count": 1
        if node.get("state") == "DONE" and not error
        else (0 if denied else None),
        **counters,
    }


def monitored_process(argv, stdin, cwd, *, timeout=120):
    """Incremental NDJSON reader: kill before processing the next event, even finish."""
    started = time.monotonic()
    environment = subscription_environment()
    environment["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
    audit: dict[str, Any] = {
        "failure_kind": None,
        "events": [],
        "tool_attempt_count": 0,
        "tool_execution_count": 0,
        "blocked_by_wrapper": False,
        "external_data_received": False,
        "structured_output": None,
    }
    for counter_key in (
        "external_network_success_count",
        "external_file_read_success_count",
        "external_command_success_count",
        "subagent_success_count",
        "mcp_success_count",
    ):
        audit[counter_key] = 0
    hashes = {"stdout": hashlib.sha256(), "stderr": hashlib.sha256()}
    buffer = b""
    pending = memoryview(stdin.encode())
    with subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=environment,
        start_new_session=True,
    ) as process:
        assert (
            process.stdin is not None and process.stdout is not None and process.stderr is not None
        )
        try:
            with selectors.DefaultSelector() as selector:
                for stream, kind in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, kind)
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
                total = 0
                while selector.get_map():
                    if time.monotonic() - started > timeout:
                        audit["failure_kind"] = "timeout"
                        break
                    for key, _ in selector.select(0.1):
                        if key.data == "stdin":
                            try:
                                sent = os.write(key.fd, pending[:65536])
                                pending = pending[sent:]
                            except BrokenPipeError:
                                pending = memoryview(b"")
                            if not pending:
                                selector.unregister(key.fileobj)
                                process.stdin.close()
                            continue
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        hashes[key.data].update(chunk)
                        total += len(chunk)
                        if total > 8_000_000:
                            audit["failure_kind"] = "STREAM_LIMIT"
                            break
                        if key.data == "stderr":
                            # Never retain auth diagnostics. Only a count/hash.
                            continue
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            if not line.strip():
                                continue
                            try:
                                event = json.loads(line)
                                if not isinstance(event, dict):
                                    raise ValueError("object required")
                            except ValueError:
                                audit["failure_kind"] = "INVALID_STREAM"
                                break
                            nodes = list(tool_nodes(event))
                            if nodes:
                                # This precedes all result admission, including already-buffered output.
                                audit["failure_kind"] = "PIT_TOOL_ATTEMPT"
                                kill_group(process)
                                audit["blocked_by_wrapper"] = True
                                audit["kill_after_start_seconds"] = time.monotonic() - started
                                audit["tool_attempt_count"] = len(nodes)
                                first = tool_audit(nodes[0])
                                audit.update(first)
                                audit["events"].append({"event": "tool_attempt", **first})
                                break
                            event_kind = event.get("event")
                            entry = {"event": event_kind, "event_hash": digest(event)}
                            if event_kind == "init":
                                init = event.get("init", event)
                                entry.update(
                                    {
                                        k: init.get(k)
                                        for k in (
                                            "agent",
                                            "model",
                                            "cwd",
                                            "tools",
                                            "permission_mode",
                                        )
                                    }
                                )
                                if "initialization" in audit:
                                    audit["failure_kind"] = "INVALID_STREAM"
                                audit["initialization"] = entry
                            elif event_kind == "result":
                                if "result" in audit:
                                    audit["failure_kind"] = "INVALID_STREAM"
                                result = event.get("result", {})
                                audit["result"] = {
                                    k: result.get(k) for k in ("status", "structured_output")
                                }
                            audit["events"].append(entry)
                        if audit["failure_kind"]:
                            break
                    if audit["failure_kind"]:
                        break
                if buffer.strip() and not audit["failure_kind"]:
                    audit["failure_kind"] = "INVALID_STREAM"
        except BaseException:
            audit["failure_kind"] = audit["failure_kind"] or "interrupted"
            raise
        finally:
            if audit["failure_kind"] and not audit["blocked_by_wrapper"]:
                kill_group(process)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                kill_group(process)
                process.wait(timeout=5)
                audit["failure_kind"] = audit["failure_kind"] or "timeout"
    audit["exit_code"] = process.returncode
    audit["duration_seconds"] = time.monotonic() - started
    audit.update({k + "_hash": h.hexdigest() for k, h in hashes.items()})
    result = audit.get("result", {})
    if not audit["failure_kind"]:
        if process.returncode or result.get("status") != "SUCCESS":
            audit["failure_kind"] = "provider_failure"
        elif not isinstance(result.get("structured_output"), dict):
            audit["failure_kind"] = "schema_failure"
        else:
            audit["structured_output"] = result["structured_output"]
    if audit["failure_kind"]:
        audit["structured_output"] = None
        audit.pop("result", None)
    return audit


def runtime_policy_log(logfile):
    # Only allowlisted config signatures are extracted; never store full CLI logs.
    raw = logfile.read_text(errors="replace") if logfile.exists() else ""
    settings_lines = [
        line for line in raw.splitlines() if "CLI settings initialized: permissions=" in line
    ]
    populated = [line for line in raw.splitlines() if "populatePermissionConfig(" in line]
    return {
        "deny_rules_loaded": bool(settings_lines)
        and all(any(rule in line.split("Deny:")[-1] for line in settings_lines) for rule in DENIES),
        "settings_signature_present": bool(settings_lines),
        "loaded_rule_names": [
            rule for rule in DENIES if any(rule in line for line in settings_lines)
        ],
        "sandbox_runtime_confirmed": any(
            "enableTerminalSandbox=true" in line for line in populated
        ),
        "non_workspace_disabled_confirmed": any(
            "allowNonWorkspaceAccess=false" in line for line in populated
        ),
        "log_hash": hashlib.sha256(raw.encode()).hexdigest(),
    }


def quarantine_call(exact_prompt, *, executable, cli_version="1.2.2", timeout=120):
    with tempfile.TemporaryDirectory(prefix="qve-quarantine-") as temp:
        cwd = Path(temp)
        agent = cwd / ".agents/agents/qve-pit-analyst/agent.md"
        agent.parent.mkdir(parents=True)
        definition = antigravity_agent_definition(exact_prompt["system"])
        agent.write_text(definition)
        workspace = verify_workspace(cwd)
        logfile = cwd / "cli.log"
        argv = [
            executable,
            "--agent",
            AGENT,
            "--model",
            "gemini-3.1-pro-high",
            "--effort",
            "high",
            "--sandbox",
            "--disable-slash-commands",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--json-schema",
            json.dumps(exact_prompt["response_schema"]),
            "--log-file",
            str(logfile),
        ]
        content = json.dumps(
            {"task": exact_prompt["task"], "untrusted_data": exact_prompt["untrusted_data"]}
        )
        stdin = json.dumps({"event": "user", "message": {"content": content}}) + "\n"
        result = monitored_process(argv, stdin, cwd, timeout=timeout)
        result.update(runtime_policy_log(logfile))
        result.update(
            transport_policy=POLICY,
            transport_policy_hash=POLICY_HASH,
            provider_type="antigravity_cli",
            cli_version=cli_version,
            requested_model="gemini-3.1-pro-high",
            agent_name=AGENT,
            agent_definition_hash=digest(definition),
            sandbox_flag=True,
            prompt_hash=digest(exact_prompt),
            source_hashes=[digest(exact_prompt["untrusted_data"])],
            workspace=workspace,
        )
        return result


def assess_synthetic_output(result):
    """No-evidence canary contract: stream silence cannot certify external isolation."""
    output = result.get("structured_output")
    if output is not None and output != {"answer": "unavailable"}:
        result["untrusted_synthetic_response"] = output
        result["structured_output"] = None
        result.pop("result", None)
        result["failure_kind"] = "UNVERIFIED_EXTERNAL_CONTENT"
        result["unsupplied_content_emitted"] = True
        result["external_data_received"] = None
        result["external_provenance"] = (
            "unknown: retrieval, hidden execution or model memory/hallucination"
        )
        for key in (
            "external_network_success_count",
            "external_file_read_success_count",
            "external_command_success_count",
            "subagent_success_count",
            "mcp_success_count",
        ):
            result[key] = None
    return result
