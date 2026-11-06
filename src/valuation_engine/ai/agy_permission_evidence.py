"""Read-only native denial evidence for a blocked synthetic diagnostic.

No AGY/model/database is invoked here. The frozen rows originate in the owned
AGY diagnostic log, not a StockOS financial database. Failed outcomes stay failed.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from valuation_engine.ai.agy_explanation import BudgetError, PersistentBudget
from valuation_engine.ai.agy_guarded import (
    AGENT,
    CLI_SHA,
    DENIED_CHILD,
    MODEL,
    PRE_TOOL_DENIAL_MESSAGES,
    encoded,
    file_sha,
    sha,
)


def _varint(raw, index):
    value = 0
    for shift in range(0, 70, 7):
        if index >= len(raw):
            raise ValueError("INVALID_NATIVE_ROW")
        byte = raw[index]
        index += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, index
    raise ValueError("INVALID_NATIVE_ROW")


def _strings(raw, depth=0):
    if depth > 12 or len(raw) > 2_000_000:
        raise ValueError("INVALID_NATIVE_ROW")
    index, output = 0, []
    while index < len(raw):
        tag, index = _varint(raw, index)
        if tag >> 3 == 0:
            raise ValueError("INVALID_NATIVE_ROW")
        wire = tag & 7
        if wire == 0:
            _, index = _varint(raw, index)
        elif wire in (1, 5):
            index += 8 if wire == 1 else 4
        elif wire == 2:
            size, index = _varint(raw, index)
            value = raw[index : index + size]
            index += size
            if len(value) != size:
                raise ValueError("INVALID_NATIVE_ROW")
            try:
                text = value.decode()
            except UnicodeError:
                text = ""
            if text and all(ord(c) >= 32 or c in "\n\t\r" for c in text):
                output.append(text)
            elif value:
                # Protobuf bytes fields can contain opaque provider signatures.
                # They are not evidence; required tool/argument/CID strings must
                # still be found and independently validated below.
                try:
                    output.extend(_strings(value, depth + 1))
                except ValueError:
                    pass
        else:
            raise ValueError("INVALID_NATIVE_ROW")
        if index > len(raw):
            raise ValueError("INVALID_NATIVE_ROW")
    return output


def validate_permission_evidence(snapshot, result, result_path, *, readonly=False):
    expected_version = (
        "StockOSAGYNativeReadonlyDenialRowsV1" if readonly else "StockOSAGYNativeDenialRowsV1"
    )
    if (
        snapshot.get("version") != expected_version
        or snapshot.get("cli_sha256") != CLI_SHA
        or snapshot.get("owned_workspace_confirmed") is not True
        or snapshot.get("source_read_mode") != "ro_query_only"
        or any(
            type(result.get(k)) is not int or result[k] != 0
            for k in ("financial_documents_sent", "formal_database_writes")
        )
        or result.get("permission_mode") != "strict"
        or result.get("actual_model") != MODEL
        or result.get("requested_agent") != (AGENT if readonly else "CLI_DEFAULT")
        or (readonly and result.get("actual_agent") != AGENT)
        or result.get("status") != "FAIL"
        or result.get("exit_code") != (0 if readonly else -9)
        or result.get("owned_process_group_absent") is not True
        or result.get("reason")
        != ("RESULT_INVALID_JSON" if readonly else "STREAM_CONTRACT_UNVERIFIED")
    ):
        raise ValueError("NATIVE_DENIAL_SCOPE_UNVERIFIED")
    audit = result.get("hook_audit", [])
    if not audit or any(row.get("configuration_matches") is not True for row in audit):
        raise ValueError("NATIVE_DENIAL_CONFIGURATION_UNVERIFIED")
    cid = snapshot["conversation_id"]
    if {row.get("conversation_id") for row in audit} != {cid}:
        raise ValueError("NATIVE_DENIAL_CONVERSATION_MISMATCH")
    if not any(row.get("event") == "invocation" and row.get("blocked") is False for row in audit):
        raise ValueError("NATIVE_DENIAL_INVOCATION_UNVERIFIED")
    root = Path(result_path).parent.parent
    targets = root / "native-canaries/synthetic-repository"
    wanted = (
        {"view_file", "read_url_content", "search_web"}
        if readonly
        else {"run_command", "write_file", "invoke_subagent"}
    )
    steps = snapshot.get("steps", [])
    if len(steps) != 3 or {s.get("tool_name") for s in steps} != wanted:
        raise ValueError("NATIVE_DENIAL_COVERAGE_MISSING")
    observations = []
    for row in steps:
        name, index = row["tool_name"], row["index"]
        pre = [a for a in audit if a.get("event") == "pre" and a.get("step_index") == index]
        if len(pre) != 1 or pre[0].get("tool_name") != name or pre[0].get("decision") != "deny":
            raise ValueError("NATIVE_DENIAL_PRE_MISMATCH")
        if row["type"] != 132 or row["status"] != 7 or row["has_subtrajectory"] != 0:
            raise ValueError("NATIVE_DENIAL_NOT_BLOCKED")
        error = bytes.fromhex(row["error_details_hex"])
        matches = []
        for message in PRE_TOOL_DENIAL_MESSAGES:
            body = message.encode()
            if (
                len(body) < 128
                and error
                == b"\x12" + bytes([len(body)]) + body + b"\x1a" + bytes([len(body)]) + body
            ):
                matches.append(message)
        if len(matches) != 1:
            raise ValueError("NATIVE_DENIAL_MESSAGE_UNVERIFIED")
        texts = _strings(bytes.fromhex(row["step_payload_hex"]))
        if name not in texts or cid not in texts:
            raise ValueError("NATIVE_DENIAL_TOOL_MISMATCH")
        arguments = {}
        for text in texts:
            if not text.startswith("{"):
                continue
            try:
                value = json.loads(text)
            except ValueError:
                continue
            if isinstance(value, dict):
                arguments[encoded(value)] = value
        if len(arguments) != 1:
            raise ValueError("NATIVE_ARGUMENTS_UNVERIFIED")
        args = next(iter(arguments.values()))
        if name == "run_command" and (
            args.get("CommandLine") != "/usr/bin/touch " + str(targets / "command-marker")
            or args.get("BypassSandbox") is not False
        ):
            raise ValueError("NATIVE_COMMAND_TARGET_MISMATCH")
        if name == "write_file" and (
            args.get("Path") != str(targets / "write-marker") or args.get("Content") != "synthetic"
        ):
            raise ValueError("NATIVE_WRITE_TARGET_MISMATCH")
        if name == "invoke_subagent" and (
            args.get("TypeName") != DENIED_CHILD
            or not isinstance(args.get("Prompt"), str)
            or "synthetic" not in args["Prompt"].lower()
        ):
            raise ValueError("NATIVE_CHILD_TARGET_MISMATCH")
        if name == "view_file" and args.get("AbsolutePath") != snapshot.get("readonly_canary_path"):
            raise ValueError("NATIVE_READ_TARGET_MISMATCH")
        if name == "read_url_content" and not any(
            v in ("https://example.com/", "https://example.com")
            for v in args.values()
            if isinstance(v, str)
        ):
            raise ValueError("NATIVE_URL_TARGET_MISMATCH")
        if name == "search_web" and not any(
            v == "StockOS synthetic permissions canary" for v in args.values() if isinstance(v, str)
        ):
            raise ValueError("NATIVE_SEARCH_TARGET_MISMATCH")
        observations.append(
            {
                "tool_name": name,
                "step_index": index,
                "pre_args_sha256": pre[0]["args_sha256"],
                "native_args_sha256": sha(encoded(args)),
                "native_error_sha256": sha(error),
                "status": "PRE_HOOK_DENIED_NATIVE_ERROR_NO_SUBTRAJECTORY",
            }
        )
    if any((targets / name).exists() for name in ("command-marker", "write-marker")):
        raise ValueError("NATIVE_DENIAL_MARKER_EXISTS")
    return observations


class PermissionCompletionBudget(PersistentBudget):
    """Bounded diagnostic revalidation, with original failures/caps preserved."""

    def __init__(self, root, *, revalidation, record_name="permission-revalidation.json", **kwargs):
        super().__init__(root, **kwargs)
        if record_name not in ("permission-revalidation.json", "permission-revalidation-v2.json"):
            raise BudgetError("INVALID_REVALIDATION_RECORD_NAME")
        self.revalidation = revalidation
        self.record_name = record_name

    def _review(self, approval, rows, records, *, readonly):
        attempt = "attempt-0002" if readonly else "attempt-0001"
        index = 1 if readonly else 0
        if (
            len(rows) <= index
            or approval.get("attempt_id") != attempt
            or records[index]["phase"] != "diagnostic"
        ):
            raise BudgetError("PERMISSION_REVALIDATION_SCOPE_MISMATCH")
        if (
            file_sha(self._path(attempt + ".json")) != approval["reservation_sha256"]
            or file_sha(self._path(attempt + ".result.json")) != approval["outcome_sha256"]
        ):
            raise BudgetError("PERMISSION_REVALIDATION_JOURNAL_CHANGED")
        outcome = self._read(attempt + ".result.json")
        if outcome.get("status") != "FAILED":
            raise BudgetError("PERMISSION_REVALIDATION_FAILURE_MISSING")
        if (
            outcome.get("reservation_sha256") != rows[index]["sha256"]
            or outcome.get("details", {}).get("result_path") != approval["result_path"]
            or outcome.get("details", {}).get("result_sha256") != approval["result_sha256"]
        ):
            raise BudgetError("PERMISSION_REVALIDATION_OUTCOME_BINDING_MISMATCH")
        result_path, snapshot_path = Path(approval["result_path"]), Path(approval["snapshot_path"])
        for path, fingerprint in (
            (result_path, approval["result_sha256"]),
            (snapshot_path, approval["snapshot_sha256"]),
        ):
            if (
                any(p.is_symlink() for p in (path, *path.parents))
                or not path.is_file()
                or path.stat().st_size > 2_000_000
                or file_sha(path) != fingerprint
            ):
                raise BudgetError("PERMISSION_REVALIDATION_EVIDENCE_CHANGED")
        snapshot, result = (
            json.loads(snapshot_path.read_text()),
            json.loads(result_path.read_text()),
        )
        if snapshot.get("original_result_sha256") != approval["result_sha256"]:
            raise BudgetError("PERMISSION_REVALIDATION_SOURCE_BINDING_MISMATCH")
        validate_permission_evidence(snapshot, result, result_path, readonly=readonly)
        return attempt

    def _recovery(self, rows, records):
        self._owned()
        if self.revalidation is None:
            return super()._recovery(rows, records)
        stored = self._read(self.record_name)
        if encoded(stored) != encoded(self.revalidation):
            raise BudgetError("PERMISSION_REVALIDATION_DRIFT")
        approval = stored["approval"]
        authorization = self._read("authorization.json")
        if (
            stored.get("version")
            not in ("StockOSAGYPermissionRevalidationV1", "StockOSAGYPermissionRevalidationV2")
            or stored.get("decision")
            != "ENGINEERING_REVALIDATION_WITHIN_CURRENT_OWNER_AUTHORIZATION"
            or not isinstance(approval.get("policy_hash"), str)
            or not approval["policy_hash"]
            or approval.get("user_instruction") != authorization.get("user_instruction")
            or encoded(authorization.get("new_allocation_caps")) != encoded(self.caps)
            or approval.get("request_sha256")
            != authorization.get("request_binding", {}).get("request_sha256")
            or approval.get("research_binding")
            != authorization.get("request_binding", {}).get("research_binding")
        ):
            raise BudgetError("PERMISSION_REVALIDATION_AUTHORIZATION_MISMATCH")
        allowed = [self._review(approval, rows, records, readonly=False)]
        additional = stored.get("additional_reviews", [])
        if stored["version"] == "StockOSAGYPermissionRevalidationV2":
            if len(additional) != 1:
                raise BudgetError("PERMISSION_REVALIDATION_SCOPE_MISMATCH")
            allowed.append(self._review(additional[0], rows, records, readonly=True))
        elif additional:
            raise BudgetError("PERMISSION_REVALIDATION_SCOPE_MISMATCH")
        return {"approval": approval, "allowed_failed_ids": allowed}

    def reserve(self, phase, metadata=None):
        if self.revalidation is None:
            return super().reserve(phase, metadata)
        if phase not in self.caps:
            raise BudgetError("INVALID_BUDGET_PHASE")
        rows, records = self._state()
        recovery = self._recovery(rows, records)
        if (
            not isinstance(metadata, dict)
            or metadata.get("policy_hash") != recovery["approval"]["policy_hash"]
        ):
            raise BudgetError("RECOVERY_POLICY_MISMATCH")
        for row in rows:
            path = self._path(row["attempt_id"] + ".result.json")
            if not path.exists():
                raise BudgetError("UNFINISHED_ATTEMPT_REQUIRES_RECONCILIATION")
            result = self._read(path.name)
            if result.get("reservation_sha256") != row["sha256"] or (
                result.get("status") != "COMPLETED"
                and row["attempt_id"] not in recovery["allowed_failed_ids"]
            ):
                raise BudgetError("PRIOR_ATTEMPT_FAILED_OR_UNVERIFIED")
        if sum(r["phase"] == phase for r in records) >= self.caps[phase]:
            raise BudgetError("BUDGET_EXHAUSTED")
        index = len(rows) + 1
        attempt = f"attempt-{index:04d}"
        raw = self._exclusive(
            attempt + ".json",
            {
                "version": "StockOSAGYAttemptV1",
                "index": index,
                "phase": phase,
                "owner": self.owner,
                "status": "RESERVED",
                "metadata": metadata,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        self._head([*rows, {"attempt_id": attempt, "phase": phase, "sha256": sha(raw)}])
        return attempt

    def snapshot(self):
        result = super().snapshot()
        rows, records = self._state()
        recovery = self._recovery(rows, records)
        result["diagnostic_revalidated_attempts"] = (
            recovery.get("allowed_failed_ids", []) if recovery else []
        )
        return result
