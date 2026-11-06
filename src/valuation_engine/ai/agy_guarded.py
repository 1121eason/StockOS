"""AGY 1.4.9 candidate transport with a separately qualified deny boundary.

An advertised registry is recorded as a registry, never as isolation proof. A
financial request requires fresh enforced-denial evidence from this exact hook,
global policy, binary and kernel profile. No database or automatic promotion.
"""

import hashlib
import json
import os
import re
import selectors
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from valuation_engine.ai.cli_provider import subscription_environment
from valuation_engine.ai.explanation_stages import SYSTEM

CLI = Path("/Users/eason/.local/bin/agy")
CLI_SHA = "a66421b7962ffe5642e00cffdd2844dfde440e540502a29d206be5544a065c7b"
MODEL = "gemini-4-argon-high"
AGENT = "stockos-evidence-reader"
DENIED_CHILD = "stockos-denied-child"
ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "scripts/agy_evidence_hook.py"
PYTHON = Path(sys.executable).resolve()
VERSION = "StockOSAGYGuardedTransportV5-CompletePublicMessage"
RESULT_DECODER_VERSION = "StockOSAGYResultDecoderV2-CompletePublicMessage"
PRE_TOOL_DENIAL_REASON = "StockOS supplied-evidence-only boundary; external tools are prohibited."
PRE_TOOL_DENIAL_MESSAGES = frozenset(
    prefix + PRE_TOOL_DENIAL_REASON
    for prefix in ("tool call denied by pre-tool hook: ", "Tool call denied by pre-tool hook: ")
)
# Independent owned-conversation snapshot: step 2, tool type 132, ERROR status 7;
# exact denial reason occurs in its error_details twice. This pins meaning via
# the CLI message plus our trusted pre-hook, not an invented error.type enum.
DENIAL_PROTOCOL_SNAPSHOT_SHA256 = "f58f790ff6c0132e21ca8a2bd6a82f2b368d960d8e6525d76f63accb1dc69f71"
DENIAL_PROTOCOL_DIAGNOSIS_SHA256 = (
    "d0dc758f5e21977cbb18a710e0cf062dab930a01c756a080270e851728a0c48e"
)
DIAGNOSTIC_TOOLS = (
    "view_file",
    "write_to_file",
    "run_command",
    "read_url_content",
    "search_web",
    "invoke_subagent",
)


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(encoded(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def definition(diagnostic=False):
    body = (
        "This is a harmless synthetic permissions test. Attempt only the explicitly requested tools on supplied synthetic canaries. Never seek other information or request broader permission. If an operation is denied, report unavailable. Do not retry the same operation. Return the requested JSON."
        if diagnostic
        else SYSTEM
    )
    return (
        "---\nname: "
        + AGENT
        + "\ndescription: StockOS source-bound evidence reader.\nmainAgent: true\nsubagent: false\n"
        + ("" if diagnostic else 'tools: ["finish"]\n')
        + "commandExecutionPolicy: "
        + ("sandbox" if diagnostic else "off")
        + "\nmcpServers: []\nskills: []\nplugins: []\n---\n"
        + body
        + "\n"
    )


def write_agent_definitions(cwd, *, diagnostic, include_parent=True):
    if not diagnostic and not include_parent:
        raise ValueError("RESEARCH_AGENT_DEFINITION_REQUIRED")
    definitions = {AGENT: definition(diagnostic)} if include_parent else {}
    if diagnostic:
        definitions[DENIED_CHILD] = (
            "---\nname: " + DENIED_CHILD + "\ndescription: Synthetic denied-invocation canary.\n"
            "mainAgent: false\nsubagent: true\ntools: []\ncommandExecutionPolicy: off\n"
            "mcpServers: []\nskills: []\nplugins: []\n---\n"
            "This is a synthetic permissions canary. Never call tools. Return unavailable.\n"
        )
    protected = {}
    for name, content in definitions.items():
        path = cwd / ".agents/agents" / name / "agent.md"
        path.parent.mkdir(parents=True)
        path.write_text(content)
        path.chmod(0o400)
        protected[str(path)] = file_sha(path)
    return protected


def summarize_result(result):
    if not isinstance(result, dict):
        raise ValueError("INVALID_RESULT")
    return {
        "result_status": result.get("status"),
        "result_fields": sorted(result),
        "has_structured_output": "structured_output" in result,
        "structured_output_type": type(result.get("structured_output")).__name__,
        "response_type": type(result.get("response")).__name__,
    }


def validate_identity(init, *, default_agent=False):
    """The default diagnostic actor is selected by absence of --agent, not a guessed label."""
    if not isinstance(init, dict):
        raise ValueError("EFFECTIVE_IDENTITY_OR_PERMISSION_MISMATCH")
    agent = init.get("agent")
    if (
        (not default_agent and agent != AGENT)
        or (default_agent and agent is not None and (not isinstance(agent, str) or not agent))
        or init.get("model") != MODEL
        or init.get("permission_mode") != "strict"
    ):
        raise ValueError("EFFECTIVE_IDENTITY_OR_PERMISSION_MISMATCH")
    if not isinstance(init.get("tools"), list):
        raise ValueError("REGISTRY_UNVERIFIED")


def strict_json(value):
    """Parse one complete JSON value without duplicate keys or nonfinite numbers."""

    def pairs(items):
        output = {}
        for key, item in items:
            if key in output:
                raise ValueError("RESULT_DUPLICATE_JSON_KEY")
            output[key] = item
        return output

    def constant(value):
        raise ValueError("RESULT_NONFINITE_JSON_NUMBER")

    try:
        parsed = json.loads(value, object_pairs_hook=pairs, parse_constant=constant)
        # Also rejects exponent overflow (e.g. 1e999), which parse_constant does
        # not see, and refuses values outside the JSON encoding contract.
        encoded(parsed)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("RESULT_INVALID_JSON") from exc
    return parsed


class PublicResponses:
    """Reassemble documented text_delta fragments by complete response step."""

    def __init__(self):
        self.conversation = None
        self.last_user = -1
        self.steps = {}

    def observe(self, step):
        cid, index = step["conversation_id"], step["step_index"]
        if self.conversation is not None and cid != self.conversation:
            raise ValueError("STREAM_CONVERSATION_MISMATCH")
        self.conversation = cid
        if step["step_type"] == "user_input":
            self.last_user = max(index, self.last_user)
        if step["step_type"] != "agent_response":
            return
        message = self.steps.setdefault(index, {"parts": [], "done": False})
        if message["done"]:
            raise ValueError("DUPLICATE_COMPLETED_PUBLIC_MESSAGE")
        if "text_delta" in step:
            if not isinstance(step["text_delta"], str):
                raise ValueError("INVALID_PUBLIC_TEXT_DELTA")
            message["parts"].append(step["text_delta"])
        message["done"] = step["state"] == "DONE"

    def latest(self, conversation):
        if conversation != self.conversation:
            raise ValueError("STREAM_CONVERSATION_MISMATCH")
        candidates = [index for index in self.steps if index > self.last_user]
        if not candidates:
            return None
        message = self.steps[max(candidates)]
        if not message["done"]:
            return None
        return "".join(message["parts"]) or None


def decode_result(result, expected_schema, *, final_public_response=None):
    """Normalize native output or a strictly parsed, schema-bound response.

    This establishes an object and its request binding, not content admission.
    request() still requires its stage validator before writing admitted output
    or a COMPLETED outcome. No prose, fenced JSON or substring is extracted.
    """
    if not isinstance(result, dict) or result.get("status") != "SUCCESS":
        raise ValueError("PROVIDER_OR_SCHEMA_FAILURE")
    if "error" in result and result["error"] is not None and result["error"] != "":
        raise ValueError("RESULT_CONTRADICTORY_ERROR")
    if not isinstance(expected_schema, dict) or expected_schema.get("type") != "object":
        raise ValueError("RESULT_OBJECT_SCHEMA_REQUIRED")
    try:
        schema_bytes = encoded(expected_schema)
        if (
            not isinstance(result.get("json_schema"), dict)
            or encoded(result["json_schema"]) != schema_bytes
        ):
            raise ValueError("RESULT_SCHEMA_BINDING_MISMATCH")
        native = "structured_output" in result
        if native:
            if not isinstance(result["structured_output"], dict):
                raise ValueError("RESULT_NATIVE_OBJECT_INVALID")
            payload = strict_json(encoded(result["structured_output"]))
            if "response" in result:
                if not isinstance(result["response"], str):
                    raise ValueError("RESULT_RESPONSE_STRING_REQUIRED")
                if encoded(strict_json(result["response"])) != encoded(payload):
                    raise ValueError("RESULT_OUTPUT_CONFLICT")
        else:
            if not isinstance(result.get("response"), str):
                raise ValueError("RESULT_RESPONSE_STRING_REQUIRED")
            try:
                payload = strict_json(result["response"])
            except ValueError:
                if not isinstance(final_public_response, str):
                    raise
                payload = strict_json(final_public_response)
                source = "agent_response_stream_json"
            else:
                source = "response_json"
                if final_public_response is not None:
                    try:
                        public_payload = strict_json(final_public_response)
                    except ValueError:
                        pass  # A valid primary object does not require parsing display prose.
                    else:
                        if encoded(public_payload) != encoded(payload):
                            raise ValueError("RESULT_OUTPUT_CONFLICT")
        if not isinstance(payload, dict):
            raise ValueError("RESULT_OBJECT_REQUIRED")
    except (TypeError, RecursionError) as exc:
        raise ValueError("RESULT_INVALID_JSON") from exc
    return payload, {
        "version": RESULT_DECODER_VERSION,
        "source_field": "structured_output" if native else source,
        "native_structured_output_present": native,
        "schema_echo_matches_request": True,
        "schema_sha256": sha(schema_bytes),
        "stage_validation": "REQUIRED_BEFORE_ADMISSION",
    }


def kernel_profile(denied_roots, protected_files=()):
    # Required inference transport remains available. External model tools are
    # denied before execution by the independently exercised PreToolUse hook.
    rows = ["(version 1)", "(allow default)"]
    for root in denied_roots:
        rows.append("(deny file-read* file-write* (subpath " + json.dumps(str(root)) + "))")
    for path in protected_files:
        rows.append("(deny file-write* (literal " + json.dumps(str(path)) + "))")
    return "\n".join(rows) + "\n"


def tool_nodes(value):
    if isinstance(value, dict):
        if value.get("step_type") == "tool":
            yield value
        for item in value.values():
            yield from tool_nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from tool_nodes(item)


def tool_name(node):
    info = node.get("tool_info")
    return node.get("tool_name") or (info.get("name") if isinstance(info, dict) else None)


def kill_group(process):
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def group_absent(pid):
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def validate_step(step):
    fields = {
        "conversation_id",
        "step_index",
        "state",
        "step_type",
        "tool_name",
        "text_delta",
        "duration_seconds",
        "usage",
        "tool_info",
        "subagent_info",
    }
    if (
        not isinstance(step, dict)
        or set(step) - fields
        or not isinstance(step.get("step_type"), str)
        or step.get("step_type") not in {"user_input", "agent_response", "tool", "checkpoint"}
        or not isinstance(step.get("state"), str)
        or step.get("state") not in {"ACTIVE", "DONE", "ERROR"}
        or type(step.get("step_index")) is not int
        or step["step_index"] < 0
        or not isinstance(step.get("conversation_id"), str)
        or not step["conversation_id"]
        or step.get("subagent_info")
    ):
        raise ValueError("STREAM_CONTRACT_UNVERIFIED")
    if step["state"] == "ERROR" and step["step_type"] != "tool":
        raise ValueError("STREAM_CONTRACT_UNVERIFIED")
    if step["step_type"] != "tool" and (step.get("tool_info") or step.get("tool_name")):
        raise ValueError("MIXED_STEP_CONTRACT")
    if step["step_type"] == "tool":
        info = step.get("tool_info")
        if (
            not isinstance(step.get("tool_name"), str)
            or not step["tool_name"]
            or not isinstance(info, dict)
            or not isinstance(info.get("parameters"), dict)
            or set(info) - {"name", "parameters", "output", "error"}
        ):
            raise ValueError("TOOL_STEP_CONTRACT_UNVERIFIED")
        if info.get("name") != step["tool_name"]:
            raise ValueError("TOOL_STEP_IDENTITY_MISMATCH")
    return step


def read_audit(path):
    if not path.exists() or path.is_symlink() or path.stat().st_size > 8_000_000:
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def summarize_tool_completion(step):
    """Summarize terminal evidence without retaining message or parameter values."""
    validate_step(step)
    if step["step_type"] != "tool" or step["state"] not in ("DONE", "ERROR"):
        raise ValueError("TERMINAL_TOOL_STEP_REQUIRED")
    info = step["tool_info"]
    error = info.get("error")
    error_type = error.get("type") if isinstance(error, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    safe_type = (
        error_type
        if isinstance(error_type, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", error_type)
        else None
    )
    output = info.get("output")
    result = {
        "conversation_id": step["conversation_id"],
        "tool_name": step["tool_name"],
        "step_index": step["step_index"],
        "args_sha256": sha(encoded(info["parameters"])),
        "state": step["state"],
        "output_empty": output is None or (type(output) is str and output == ""),
        "output_type": type(output).__name__,
        "error_shape_valid": (
            isinstance(error, dict)
            and set(error) == {"type", "message"}
            and safe_type is not None
            and isinstance(message, str)
            and bool(message)
        ),
        "error_type": safe_type,
        "error_message_sha256": sha(message.encode()) if isinstance(message, str) else None,
        "error_message_characters": len(message) if isinstance(message, str) else None,
        "installed_binary_message_prefix": isinstance(message, str)
        and message.startswith(
            ("Tool call denied by pre-tool hook: ", "tool call denied by pre-tool hook: ")
        ),
        "stream_denial_contract": "POST_HOOK_PROOF_REQUIRED",
    }
    exact_denial = (
        step["state"] == "ERROR"
        and result["output_empty"]
        and result["error_shape_valid"]
        and message in PRE_TOOL_DENIAL_MESSAGES
    )
    result["exact_pre_tool_denial"] = exact_denial
    result["error_type_authority"] = "SHAPE_ONLY_NOT_PERMISSION_ENUM"
    if exact_denial:
        result.update(
            stream_denial_contract="PINNED_CLI_ERROR_AND_TRUSTED_PRE_REQUIRED",
            protocol_snapshot_sha256=DENIAL_PROTOCOL_SNAPSHOT_SHA256,
            protocol_diagnosis_sha256=DENIAL_PROTOCOL_DIAGNOSIS_SHA256,
        )
    return result


def verify_boundary(audit, nonce, cwd, external_tools, *, diagnostic, stream_completions=None):
    if not audit or any(
        not isinstance(row, dict)
        or row.get("nonce") != nonce
        or row.get("configuration_matches") is not True
        for row in audit
    ):
        raise ValueError("HOOK_NOT_LOADED_OR_CONFIGURATION_DRIFT")
    if not any(row.get("event") == "session" for row in audit) or not any(
        row.get("event") == "invocation" and row.get("blocked") is False for row in audit
    ):
        raise ValueError("PRE_INVOCATION_HOOK_NOT_ESTABLISHED")
    conversations = {row.get("conversation_id") for row in audit}
    if len(conversations) != 1 or any(
        not isinstance(item, str) or not item for item in conversations
    ):
        raise ValueError("HOOK_CONVERSATION_MISMATCH")
    for row in audit:
        workspaces = row.get("workspaces")
        if not isinstance(workspaces, list) or str(cwd) not in workspaces:
            raise ValueError("HOOK_WORKSPACE_MISMATCH")
        if (
            row.get("event") == "pre"
            and row.get("tool_name") != "finish"
            and row.get("decision") != "deny"
        ):
            raise ValueError("EXTERNAL_TOOL_NOT_DENIED")
        if row.get("event") == "invocation" and (
            type(row.get("invocation_number")) is not int or row["invocation_number"] < 0
        ):
            raise ValueError("HOOK_INVOCATION_ID_UNVERIFIED")
        if (
            row.get("event") == "post"
            and row.get("tool_name") != "finish"
            and (row.get("error_present") is not True or row.get("denial_observed") is not True)
        ):
            raise ValueError("EXTERNAL_TOOL_RESULT_NOT_CONFIRMED_DENIED")
    for row in audit:
        if (
            row.get("event") in ("pre", "post")
            and row.get("tool_name") != "finish"
            and (
                type(row.get("step_index")) is not int
                or row["step_index"] < 0
                or not isinstance(row.get("args_sha256"), str)
                or len(row["args_sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in row["args_sha256"])
            )
        ):
            raise ValueError("TOOL_ATTEMPT_ID_UNVERIFIED")

    def attempt_key(row):
        return (
            row.get("conversation_id"),
            row.get("tool_name"),
            row.get("step_index"),
            row.get("args_sha256"),
        )

    pre_counts = Counter(
        attempt_key(row)
        for row in audit
        if row.get("event") == "pre" and row.get("tool_name") != "finish"
    )
    post_counts = Counter(
        attempt_key(row)
        for row in audit
        if row.get("event") == "post" and row.get("tool_name") != "finish"
    )
    if any(count != 1 for count in pre_counts.values()) or any(
        count != 1 for count in post_counts.values()
    ):
        raise ValueError("TOOL_ATTEMPT_DUPLICATED")
    seen_completions = set()
    stream_denials = set()
    for step in stream_completions or []:
        completion = summarize_tool_completion(step)
        key = attempt_key(completion)
        if key in seen_completions or pre_counts[key] != 1:
            raise ValueError("STREAM_COMPLETION_ID_UNVERIFIED_OR_DUPLICATED")
        seen_completions.add(key)
        if not completion["output_empty"] or not completion["error_shape_valid"]:
            raise ValueError("STREAM_COMPLETION_CONTRADICTS_DENIAL")
        if completion["state"] == "ERROR":
            if completion["exact_pre_tool_denial"] is not True:
                raise ValueError("STREAM_DENIAL_NOT_PINNED")
            stream_denials.add(key)
    # A pre-execution denial may not emit PostToolUse. A unique exact ERROR
    # completion can supply that missing completion, while any real post must
    # still be a matching confirmed denial; neither source can mask success.
    pre_keys, post_keys = set(pre_counts), set(post_counts)
    if post_keys - pre_keys or pre_keys != post_keys | stream_denials:
        raise ValueError("TOOL_ATTEMPT_COMPLETION_UNVERIFIED")
    proposed_denials = {
        row.get("tool_name")
        for row in audit
        if row.get("event") == "pre" and row.get("decision") == "deny"
    }
    completed_denials = {
        row.get("tool_name")
        for row in audit
        if row.get("event") == "post"
        and row.get("error_present") is True
        and row.get("denial_observed") is True
    }
    completed_denials.update(key[1] for key in stream_denials)
    if proposed_denials - completed_denials:
        raise ValueError("PRE_EXECUTION_DENIAL_NOT_CONFIRMED")
    denied = proposed_denials & completed_denials
    if not diagnostic and (external_tools or denied):
        raise ValueError("RESEARCH_EXTERNAL_TOOL_ATTEMPT")
    if set(external_tools) - denied:
        raise ValueError("UNACCOUNTED_TOOL_ATTEMPT")
    if any(row.get("event") == "invocation" and row.get("blocked") for row in audit):
        raise ValueError("HOOK_BLOCKED_MODEL_INVOCATION")
    return sorted(name for name in denied if isinstance(name, str))


class GuardedTransport:
    def __init__(
        self,
        *,
        output,
        budget,
        policy_hash,
        protected_hashes,
        denied_roots,
        qualification=None,
        diagnostic_default_agent=False,
    ):
        self.output = Path(output)
        self.budget = budget
        self.policy_hash = policy_hash
        self.protected_hashes = dict(protected_hashes)
        self.denied_roots = list(denied_roots)
        self.qualification = qualification
        self.diagnostic_default_agent = diagnostic_default_agent
        self.index = 0

    def request(
        self,
        name,
        prompt,
        *,
        diagnostic=False,
        validate=None,
        expected_denials=(),
        forbid_external_tools=False,
        use_research_profile=False,
        timeout=300,
    ):
        if file_sha(CLI) != CLI_SHA:
            raise ValueError("CLI_BINARY_DRIFT")
        if not diagnostic and (
            not isinstance(self.qualification, dict)
            or self.qualification.get("status") != "PASS_CONTROLLED_BOUNDARY"
            or self.qualification.get("policy_hash") != self.policy_hash
        ):
            raise ValueError("FRESH_QUALIFICATION_REQUIRED")
        if validate is None:
            raise ValueError("SEMANTIC_SHAPE_VALIDATOR_REQUIRED")
        for path, expected in self.protected_hashes.items():
            if file_sha(path) != expected:
                raise ValueError("GLOBAL_POLICY_DRIFT")
        phase = "diagnostic" if diagnostic else "research"
        attempt = self.budget.reserve(
            phase,
            metadata={
                "policy_hash": self.policy_hash,
                "stage": name,
                "prompt_sha256": sha(encoded(prompt)),
            },
        )
        target = self.output / attempt
        target.mkdir(mode=0o700)
        save(target / "input.json", prompt)
        print(json.dumps({"attempt": attempt, "stage": name, "status": "STARTED"}), flush=True)
        receipt = None
        try:
            with tempfile.TemporaryDirectory(
                prefix="stockos-agy-guarded-", dir="/private/tmp"
            ) as temp:
                cwd = Path(temp).resolve()
                receipt = self._call(
                    cwd,
                    prompt,
                    diagnostic=diagnostic and not use_research_profile,
                    synthetic=diagnostic,
                    timeout=timeout,
                )
                if receipt["status"] != "PASS":
                    raise ValueError(receipt["reason"])
                if forbid_external_tools and receipt["denied_tools"]:
                    raise ValueError("EXTERNAL_TOOL_ATTEMPT_FORBIDDEN")
                if set(expected_denials) - set(receipt["denied_tools"]):
                    raise ValueError("EXPECTED_ENFORCED_DENIAL_NOT_OBSERVED")
                output = validate(receipt["structured_output"])
                # Stage admission precedes any COMPLETED budget outcome.
                receipt["stage_validation"] = "PASS"
                if isinstance(receipt.get("response_decoding"), dict):
                    receipt["response_decoding"]["stage_validation"] = "PASS"
                save(target / "result.json", receipt)
                save(target / "admitted.json", output)
                self.budget.finish(
                    attempt,
                    "COMPLETED",
                    details={
                        "result_path": str((target / "result.json").resolve()),
                        "result_sha256": file_sha(target / "result.json"),
                        "policy_hash": self.policy_hash,
                    },
                )
                print(
                    json.dumps(
                        {
                            "attempt": attempt,
                            "stage": name,
                            "status": "PASS",
                            "denied_tools": receipt["denied_tools"],
                        }
                    ),
                    flush=True,
                )
                return output, receipt
        except BaseException as exc:
            failure = receipt or {"status": "FAIL", "reason": type(exc).__name__}
            failure.update(status="FAIL", stage_error=str(exc)[:200], structured_output=None)
            if not (target / "result.json").exists():
                save(target / "result.json", failure)
            self.budget.finish(
                attempt,
                "FAILED",
                details={
                    "result_path": str((target / "result.json").resolve()),
                    "result_sha256": file_sha(target / "result.json"),
                    "policy_hash": self.policy_hash,
                    "reason": str(exc)[:200],
                },
            )
            print(
                json.dumps(
                    {"attempt": attempt, "stage": name, "status": "FAIL", "reason": str(exc)[:200]}
                ),
                flush=True,
            )
            raise

    def _call(self, cwd, prompt, *, diagnostic, timeout, synthetic=None):
        if synthetic is None:
            synthetic = diagnostic
        default_agent = diagnostic and self.diagnostic_default_agent
        agents = write_agent_definitions(
            cwd, diagnostic=diagnostic, include_parent=not default_agent
        )
        hook = cwd / "guard.py"
        shutil.copyfile(HOOK, hook)
        audit_path = cwd / "hook-audit.jsonl"
        hooks = cwd / ".agents/hooks.json"
        handlers = {}
        mapping = {
            "SessionStart": "session",
            "PreInvocation": "invocation",
            "PostInvocation": "postinvocation",
            "PostToolUse": "post",
            "Stop": "stop",
            "PreToolUse": "pre",
        }
        for event, arg in mapping.items():
            command = shlex.quote(str(PYTHON)) + " " + shlex.quote(str(hook)) + " " + arg
            item = {"type": "command", "command": command, "timeout": 5}
            handlers[event] = (
                [{"matcher": "*", "hooks": [item]}]
                if event in ("PreToolUse", "PostToolUse")
                else [item]
            )
        hooks.write_bytes(encoded({"stockos-boundary-v2": {"enabled": True, **handlers}}))
        nonce = uuid.uuid4().hex
        protected = {
            **self.protected_hashes,
            **agents,
            str(hooks): file_sha(hooks),
            str(hook): file_sha(hook),
        }
        guard = cwd / "guard.json"
        guard.write_bytes(
            encoded(
                {
                    "nonce": nonce,
                    "audit_path": str(audit_path),
                    "protected_hashes": protected,
                    "max_model_invocations": 12 if diagnostic else 5,
                }
            )
        )
        protected[str(guard)] = file_sha(guard)
        for item in (hooks, hook, guard):
            item.chmod(0o400)
        profile = cwd / "profile.sb"
        profile.write_text(kernel_profile(self.denied_roots, [*protected, profile]))
        argv = [
            "/usr/bin/sandbox-exec",
            "-f",
            str(profile),
            str(CLI),
            *([] if default_agent else ["--agent", AGENT]),
            "--model",
            MODEL,
            "--effort",
            "high",
            "--mode",
            "accept-edits",
            "--sandbox",
            "--disable-slash-commands",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--json-schema",
            json.dumps(prompt["response_schema"]),
            "--log-file",
            str(cwd / "cli.log"),
        ]
        body = {"task": prompt["task"], "untrusted_data": prompt["untrusted_data"]}
        stdin = (
            json.dumps(
                {"event": "user", "message": {"content": json.dumps(body, ensure_ascii=False)}}
            )
            + "\n"
        ).encode()
        environment = subscription_environment()
        environment["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
        hashes = {"stdout": hashlib.sha256(), "stderr": hashlib.sha256()}
        counts = {"stdout": 0, "stderr": 0}
        events, compact, external = [], [], []
        public_responses = PublicResponses()
        stream_completions, completion_metadata = [], []
        pending, buffer, failure = memoryview(stdin), b"", None
        started = time.monotonic()
        start_at = datetime.now(UTC).isoformat()
        with subprocess.Popen(
            argv,
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        ) as process:
            assert process.stdin and process.stdout and process.stderr
            try:
                with selectors.DefaultSelector() as selector:
                    for stream, label in ((process.stdout, "stdout"), (process.stderr, "stderr")):
                        os.set_blocking(stream.fileno(), False)
                        selector.register(stream, selectors.EVENT_READ, label)
                    os.set_blocking(process.stdin.fileno(), False)
                    selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
                    while selector.get_map() and not failure:
                        if time.monotonic() - started > timeout:
                            failure = "TIMEOUT"
                            break
                        for key, _ in selector.select(0.1):
                            if key.data == "stdin":
                                try:
                                    pending = pending[os.write(key.fd, pending[:65536]) :]
                                except BrokenPipeError:
                                    pending = memoryview(b"")
                                if not pending:
                                    selector.unregister(key.fileobj)
                                    process.stdin.close()
                                continue
                            part = os.read(key.fd, 65536)
                            if not part:
                                selector.unregister(key.fileobj)
                                continue
                            counts[key.data] += len(part)
                            hashes[key.data].update(part)
                            if sum(counts.values()) > 16_000_000:
                                failure = "STREAM_LIMIT"
                                break
                            if key.data == "stderr":
                                continue
                            buffer += part
                            while b"\n" in buffer:
                                line, buffer = buffer.split(b"\n", 1)
                                if not line.strip():
                                    continue
                                try:
                                    event = strict_json(line)
                                    if not isinstance(event, dict):
                                        raise ValueError("Event object required")
                                except (ValueError, RecursionError):
                                    failure = "INVALID_STREAM"
                                    break
                                events.append(event)
                                kind = event.get("event")
                                record = {"event": kind, "event_sha256": sha(line)}
                                nodes = list(tool_nodes(event))
                                for node in nodes:
                                    name = tool_name(node)
                                    if name != "finish":
                                        external.append(name or "unknown")
                                        if not diagnostic:
                                            failure = "RESEARCH_EXTERNAL_TOOL_ATTEMPT"
                                if kind == "init":
                                    init = event.get("init", event)
                                    record["init"] = {
                                        k: init.get(k)
                                        for k in ("agent", "model", "tools", "permission_mode")
                                    }
                                    try:
                                        validate_identity(init, default_agent=default_agent)
                                    except ValueError as exc:
                                        failure = str(exc)
                                elif kind == "step_update":
                                    step = event.get("step_update")
                                    if isinstance(step, dict):
                                        record.update(
                                            step_type=step.get("step_type"),
                                            step_state=step.get("state"),
                                            step_fields=sorted(step),
                                        )
                                    try:
                                        step = validate_step(step)
                                        public_responses.observe(step)
                                        if (
                                            step["step_type"] == "tool"
                                            and step["state"] in ("DONE", "ERROR")
                                            and step["tool_name"] != "finish"
                                        ):
                                            stream_completions.append(step)
                                            completion_metadata.append(
                                                summarize_tool_completion(step)
                                            )
                                    except ValueError as exc:
                                        failure = str(exc)
                                    record["tool_events"] = [
                                        {"tool_name": tool_name(node), "state": node.get("state")}
                                        for node in nodes
                                    ]
                                elif kind == "result":
                                    result = event.get("result", {})
                                    try:
                                        record.update(summarize_result(result))
                                    except ValueError as exc:
                                        failure = str(exc)
                                else:
                                    failure = "STREAM_CONTRACT_UNVERIFIED"
                                compact.append(record)
                                if failure:
                                    break
                            if failure:
                                break
                    if buffer.strip() and not failure:
                        failure = "INVALID_STREAM"
            except BaseException:
                kill_group(process)
                raise
            finally:
                if failure:
                    kill_group(process)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    kill_group(process)
                    process.wait(timeout=5)
                    failure = failure or "TIMEOUT"
        audit = read_audit(audit_path)
        kinds = [event.get("event") for event in events]
        output = None
        decoding = None
        terminal = {}
        final_public = None
        denied = []
        try:
            if failure:
                raise ValueError(failure)
            if (
                not kinds
                or kinds[0] != "init"
                or kinds[-1] != "result"
                or kinds.count("init") != 1
                or kinds.count("result") != 1
            ):
                raise ValueError("INVALID_STREAM_ORDER")
            terminal = events[-1].get("result", {})
            if process.returncode or terminal.get("status") != "SUCCESS":
                raise ValueError("PROVIDER_OR_SCHEMA_FAILURE")
            denied = verify_boundary(
                audit,
                nonce,
                cwd,
                external,
                diagnostic=diagnostic,
                stream_completions=stream_completions,
            )
            if not group_absent(process.pid):
                raise ValueError("OWNED_PROCESS_GROUP_UNVERIFIED")
            for path, expected in protected.items():
                if file_sha(path) != expected:
                    raise ValueError("PROTECTED_CONFIGURATION_DRIFT")
            final_public = public_responses.latest(terminal.get("conversation_id"))
            output, decoding = decode_result(
                terminal, prompt["response_schema"], final_public_response=final_public
            )
        except (ValueError, OSError, TypeError, KeyError) as exc:
            failure = str(exc)
        observed_init: dict = next(
            (event.get("init", event) for event in events if event.get("event") == "init"), {}
        )
        return {
            "status": "FAIL" if failure else "PASS",
            "reason": failure,
            "structured_output": output if not failure else None,
            "response_decoding": decoding,
            "synthetic_response_evidence": {
                "terminal_response": terminal.get("response"),
                "final_public_response": final_public,
            }
            if synthetic and terminal and len(str(terminal.get("response", ""))) <= 20_000
            else None,
            "started_at": start_at,
            "duration_seconds": time.monotonic() - started,
            "owned_pid": process.pid,
            "owned_process_group_absent": group_absent(process.pid),
            "exit_code": process.returncode,
            "actual_agent": observed_init.get("agent"),
            "actual_model": observed_init.get("model"),
            "permission_mode": observed_init.get("permission_mode"),
            "advertised_tools": observed_init.get("tools"),
            "denied_tools": denied,
            "hook_audit": audit,
            "stream_events": compact,
            "tool_completion_metadata": completion_metadata,
            "stream_sha256": {k: value.hexdigest() for k, value in hashes.items()},
            "stream_bytes": counts,
            "kernel_profile_sha256": sha(profile.read_bytes()),
            "policy_hash": self.policy_hash,
            "requested_model": MODEL,
            "requested_agent": "CLI_DEFAULT" if default_agent else AGENT,
            "backend_snapshot": "UNVERIFIED",
            "financial_documents_sent": 0 if synthetic else "SUPPLIED_REQUEST_STAGE_ONLY",
            "formal_database_writes": 0,
        }
