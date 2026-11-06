"""Pure AGY stream admission and local, non-resetting candidate-run bookkeeping.

No provider, process, network or database API is called here. A valid stream is
not proof of an enforced pre-execution sandbox or of backend model identity.
"""

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PINNED_QUARTER = "FY2027-Q2"
PINNED_REQUEST_SHA256 = "32c9e4cf9760d5eb612a794437e7b9b6aab3fff02e6b74d97fd58672eaef1225"
PINNED_RESEARCH_BINDING = "b788165e2f6687515a13de00478d7637afd9f84b74f57e6224c8d7f3514fba40"
KNOWN_EVENTS = frozenset({"init", "step_update", "result"})
PHASE_CAPS = {"diagnostic": 7, "research": 22}
RECOVERY_APPROVAL_VERSION = "StockOSAGYRecoveryApprovalV1"
RECOVERY_AMENDMENT_VERSION = "StockOSAGYRecoveryAmendmentV1"
RECOVERY_FILE = "recovery-amendment.json"
RECOVERABLE_ATTEMPT = "attempt-0001"
RECOVERABLE_REASON = "AGY_NO_EXTERNAL_TOOLS_CONTRACT_UNVERIFIED"
STARTUP_REPAIR_APPROVAL_VERSION = "StockOSAGYStartupRepairApprovalV1"
STARTUP_REPAIR_AMENDMENT_VERSION = "StockOSAGYStartupRepairAmendmentV1"
STARTUP_REPAIR_FILE = "startup-repair-amendment.json"
STARTUP_REPAIR_ATTEMPT = "attempt-0002"
STARTUP_REPAIR_CONVERSATION = "89cf0a5e-53e4-4c1a-bd14-3522bb307b7f"
STARTUP_REPAIR_ERROR_PREFIX = (
    "failed to construct executor: failed to resolve components: unknown component: tool "
    '"call_mcp_tool" not found in registry'
)
PLUGIN_STARTUP_REPAIR_APPROVAL_VERSION = "StockOSAGYPluginStartupRepairApprovalV1"
PLUGIN_STARTUP_REPAIR_AMENDMENT_VERSION = "StockOSAGYPluginStartupRepairAmendmentV1"
PLUGIN_STARTUP_REPAIR_FILE = "plugin-startup-repair-amendment.json"
PLUGIN_STARTUP_REPAIR_ATTEMPT = "attempt-0003"
PLUGIN_STARTUP_REPAIR_CONVERSATION = "f4cc5ee9-02b3-4003-872c-433e62dabacf"
PLUGIN_STARTUP_NOTICE = (
    "The Data Agent Kit plugin needs to be configured.\n"
    "Do this right away as critical functionality will either be missing or not work correctly "
    "if the plugin is not configured.\n"
)
PLUGIN_STARTUP_PAYLOAD_SHA256 = "4d5b581756019cb9b7dd1d90bc642c788ae58b8c025acfff0ba444b114d835a1"
DENIAL_PROTOCOL_REPAIR_APPROVAL_VERSION = "StockOSAGYDenialProtocolRepairApprovalV1"
DENIAL_PROTOCOL_REPAIR_AMENDMENT_VERSION = "StockOSAGYDenialProtocolRepairAmendmentV1"
DENIAL_PROTOCOL_REPAIR_FILE = "denial-protocol-repair-amendment.json"
DENIAL_PROTOCOL_REPAIR_ATTEMPT = "attempt-0004"
DENIAL_PROTOCOL_REPAIR_CONVERSATION = "f9411549-d707-4b2f-99c7-4d35b2f4caf0"
DENIAL_PROTOCOL_ARGS_SHA256 = "821950479fb3968eacc0ebc9db769cb54a4eea18997856c360ca40f36b654c6a"
DENIAL_PROTOCOL_ERROR_SHA256 = "f9c8307a8877442b60d916b3667ad9047d0b2c6ca6493d736ca57a6535aa1468"
DENIAL_PROTOCOL_MESSAGE = (
    "tool call denied by pre-tool hook: StockOS supplied-evidence-only boundary; "
    "external tools are prohibited."
)
PLAN_MODE_REPAIR_APPROVAL_VERSION = "StockOSAGYPlanModeRepairApprovalV1"
PLAN_MODE_REPAIR_AMENDMENT_VERSION = "StockOSAGYPlanModeRepairAmendmentV1"
PLAN_MODE_REPAIR_FILE = "plan-mode-repair-amendment.json"
PLAN_MODE_REPAIR_ATTEMPT = "attempt-0005"
PLAN_MODE_REPAIR_CONVERSATION = "5e5da5fe-cdca-4659-9bf0-9b938b4e90d2"
PLAN_MODE_DENIALS = (
    ("view_file", 2, "dc68d622165c7db671fe6e37612459c6023fe133efd8724a12fe7b55f90685d9"),
    ("view_file", 3, "21162c2792d8282a4421d6cc2071c0468f4ff0d738a099c5eaea9d50187d539b"),
    ("view_file", 4, "9006fec9a8ac14492f673d276deef3f657b776518db311d4e3a734f8632903c6"),
    ("read_url_content", 5, "80c1e7b11e1ee471db08b45d93ffe3edc4c063d377b9f67b238d3bf93c4a93e7"),
    ("search_web", 6, "cc6f90dc1b4dd2400c8c29ecfc51e96968b41f4858e80eaca3d9e21d35e1be25"),
)
PLAN_MODE_RESPONSE_SHA256 = "3bf86af0fb685426857b6c5d1d483b52d020cafec832ef07c684fb788e59d239"


def _bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _sha(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def _tools(value: Any):
    if isinstance(value, dict):
        if value.get("step_type") == "tool":
            yield value
        for item in value.values():
            yield from _tools(item)
    elif isinstance(value, list):
        for item in value:
            yield from _tools(item)


def validate_events(
    events: Any, expected_agent: str, expected_model: str, *, exit_code: int = 0
) -> dict:
    """Fail closed and return an allowlisted summary of an entire NDJSON stream.

    Only the terminal structured-answer emitter ``finish`` is allowlisted. This
    checks captured events after the fact; callers still need a live enforcement
    boundary, fresh synthetic qualification and a process-cleanup receipt.
    """
    result: dict[str, Any] = {
        "status": "FAIL",
        "reason": "INVALID_STREAM",
        "structured_output": None,
        "actual_agent": None,
        "actual_model": None,
        "advertised_tools": None,
        "tool_attempt_count": 0,
        "finish_event_count": 0,
        "event_count": 0,
        "tool_isolation_verified": False,
        "model_identity": "CLI_REPORTED_ONLY",
        "backend_snapshot": "UNVERIFIED",
        "preexecution_enforcement": "NOT_ESTABLISHED_BY_STREAM_VALIDATION",
    }

    def fail(reason: str) -> dict:
        result.update(status="FAIL", reason=reason, structured_output=None)
        return result

    if not isinstance(events, list) or not events or not all(isinstance(e, dict) for e in events):
        return fail("INVALID_STREAM")
    result["event_count"] = len(events)
    # A live monitor may stop at init before terminal output. Keep explicit
    # observed metadata for that failed diagnostic without admitting any answer.
    observed_init = next((event for event in events if event.get("event") == "init"), None)
    if observed_init is not None:
        observed = observed_init.get("init", observed_init)
        if isinstance(observed, dict):
            result.update(
                actual_agent=observed.get("agent"),
                actual_model=observed.get("model"),
                advertised_tools=observed.get("tools"),
            )
    try:
        result["stream_sha256"] = _sha(events)
        nodes = list(_tools(events))
    except (TypeError, ValueError, RecursionError):
        return fail("INVALID_STREAM")
    external = []
    for node in nodes:
        info = node.get("tool_info")
        name = node.get("tool_name") or (info.get("name") if isinstance(info, dict) else None)
        if name == "finish":
            result["finish_event_count"] += 1
        else:
            external.append(name if isinstance(name, str) else "unknown")
    result["tool_attempt_count"] = len(external)
    if external:
        result["observed_forbidden_tools"] = sorted(set(external))
        return fail("PIT_TOOL_ATTEMPT")
    kinds = [event.get("event") for event in events]
    if any(not isinstance(kind, str) or kind not in KNOWN_EVENTS for kind in kinds):
        return fail("STREAM_CONTRACT_UNVERIFIED")
    if kinds.count("init") != 1 or kinds[0] != "init":
        return fail("INVALID_INITIALIZATION_ORDER")
    initial = events[0].get("init", events[0])
    if not isinstance(initial, dict):
        return fail("INVALID_INITIALIZATION")
    agent, model, tools = (initial.get(key) for key in ("agent", "model", "tools"))
    result.update(actual_agent=agent, actual_model=model, advertised_tools=tools)
    if agent != expected_agent or not isinstance(agent, str) or not agent:
        return fail("AGENT_IDENTITY_MISMATCH")
    if model != expected_model or not isinstance(model, str) or not model:
        return fail("MODEL_IDENTITY_MISMATCH")
    if not isinstance(tools, list) or not all(isinstance(tool, str) for tool in tools):
        return fail("ISOLATION_UNVERIFIED")
    if len(tools) != len(set(tools)) or set(tools) - {"finish"}:
        return fail("ISOLATION_UNVERIFIED")
    if kinds.count("result") != 1 or kinds[-1] != "result":
        return fail("INVALID_TERMINAL_ORDER")
    for event in events[1:-1]:
        if not isinstance(event.get("step_update"), dict):
            return fail("STREAM_CONTRACT_UNVERIFIED")
    terminal = events[-1].get("result")
    if not isinstance(terminal, dict) or terminal.get("status") != "SUCCESS":
        return fail("PROVIDER_FAILURE")
    if type(exit_code) is not int or exit_code != 0:
        return fail("PROCESS_FAILURE")
    output = terminal.get("structured_output")
    if not isinstance(output, dict):
        return fail("SCHEMA_FAILURE")
    result.update(
        status="PASS", reason=None, structured_output=output, tool_isolation_verified=True
    )
    return result


@dataclass(frozen=True)
class RequestBinding:
    ticker: str
    quarter: str
    checkpoint: str
    information_cutoff: str
    request_sha256: str
    research_binding: str

    @classmethod
    def from_request(
        cls,
        request: dict,
        *,
        expected_request_sha256: str = PINNED_REQUEST_SHA256,
        expected_research_binding: str = PINNED_RESEARCH_BINDING,
        expected_quarter: str = PINNED_QUARTER,
    ) -> "RequestBinding":
        if (
            not isinstance(request, dict)
            or request.get("version") != "StockOSAIExplanationRequestV1"
            or request.get("ticker") != "NVDA"
            or request.get("quarter") != expected_quarter
            or request.get("source_scope") != "current_previous"
            or request.get("research_binding") != expected_research_binding
            or _sha(request) != expected_request_sha256
        ):
            raise ValueError("REQUEST_BINDING_MISMATCH")
        for key in ("checkpoint", "information_cutoff"):
            value = request.get(key)
            if not isinstance(value, str):
                raise ValueError("REQUEST_TIMESTAMP_INVALID")
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("REQUEST_TIMESTAMP_INVALID")
        return cls(
            ticker=request["ticker"],
            quarter=request["quarter"],
            checkpoint=request["checkpoint"],
            information_cutoff=request["information_cutoff"],
            request_sha256=expected_request_sha256,
            research_binding=expected_research_binding,
        )

    def validate_request(self, request: dict) -> None:
        candidate = type(self).from_request(
            request,
            expected_request_sha256=self.request_sha256,
            expected_research_binding=self.research_binding,
            expected_quarter=self.quarter,
        )
        if candidate != self:
            raise ValueError("REQUEST_BINDING_MISMATCH")

    def as_dict(self) -> dict:
        return asdict(self)


class BudgetError(RuntimeError):
    pass


class PersistentBudget:
    """One owner, append-only reservations/outcomes, immutable limits, no reset.

    Interrupted reservations, failed outcomes, missing/tampered journals and
    unrecognized locks halt new reservations. Locks are never stolen or repaired.
    The supplied root must be the one shared by all StockOS-controlled requests.
    """

    def __init__(self, root: Path, *, diagnostic_cap: int = 7, research_cap: int = 22):
        self.root = Path(root).absolute()
        self.caps = {"diagnostic": diagnostic_cap, "research": research_cap}
        if any(
            type(cap) is not int or not 0 <= cap <= PHASE_CAPS[phase]
            for phase, cap in self.caps.items()
        ):
            raise BudgetError("INVALID_BUDGET_CAP")
        self._configured_caps = tuple(sorted(self.caps.items()))
        self.owner = uuid.uuid4().hex
        self._lock_bytes: bytes | None = None
        self._lock_inode: tuple[int, int] | None = None

    def _configured(self) -> dict[str, int]:
        if (
            not isinstance(self.caps, dict)
            or set(self.caps) != set(PHASE_CAPS)
            or any(
                type(cap) is not int or not 0 <= cap <= PHASE_CAPS[phase]
                for phase, cap in self.caps.items()
            )
        ):
            raise BudgetError("INVALID_BUDGET_CAP")
        expected = dict(self._configured_caps)
        if self.caps != expected:
            raise BudgetError("BUDGET_POLICY_DRIFT")
        return expected

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()

    def _path(self, name: str) -> Path:
        path = self.root / name
        if path.is_symlink():
            raise BudgetError("SYMLINK_STATE_REFUSED")
        return path

    def _read(self, name: str) -> dict:
        try:
            path = self._path(name)
            if not path.is_file() or path.stat().st_size > 2_000_000:
                raise BudgetError("INVALID_BUDGET_STATE")
            value = json.loads(path.read_bytes())
            if not isinstance(value, dict):
                raise BudgetError("INVALID_BUDGET_STATE")
            return value
        except (OSError, ValueError, RecursionError) as exc:
            raise BudgetError("INVALID_BUDGET_STATE") from exc

    def _exclusive(self, name: str, value: dict) -> bytes:
        raw = _bytes(value)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(self._path(name), flags, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return raw

    def _head(
        self,
        rows: list[dict],
        *,
        recovery_sha256: str | None = None,
        startup_repair_sha256: str | None = None,
        plugin_startup_repair_sha256: str | None = None,
        denial_protocol_repair_sha256: str | None = None,
        plan_mode_repair_sha256: str | None = None,
    ) -> None:
        head: dict[str, Any] = {"reservations": rows}
        previous = self._read("head.json")
        if recovery_sha256 is None:
            recovery_sha256 = previous.get("recovery_sha256")
        if recovery_sha256 is not None:
            head["recovery_sha256"] = recovery_sha256
        if startup_repair_sha256 is None:
            startup_repair_sha256 = previous.get("startup_repair_sha256")
        if startup_repair_sha256 is not None:
            head["startup_repair_sha256"] = startup_repair_sha256
        if plugin_startup_repair_sha256 is None:
            plugin_startup_repair_sha256 = previous.get("plugin_startup_repair_sha256")
        if plugin_startup_repair_sha256 is not None:
            head["plugin_startup_repair_sha256"] = plugin_startup_repair_sha256
        if denial_protocol_repair_sha256 is None:
            denial_protocol_repair_sha256 = previous.get("denial_protocol_repair_sha256")
        if denial_protocol_repair_sha256 is not None:
            head["denial_protocol_repair_sha256"] = denial_protocol_repair_sha256
        if plan_mode_repair_sha256 is None:
            plan_mode_repair_sha256 = previous.get("plan_mode_repair_sha256")
        if plan_mode_repair_sha256 is not None:
            head["plan_mode_repair_sha256"] = plan_mode_repair_sha256
        fd, temp = tempfile.mkstemp(prefix=".head-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(_bytes(head))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self._path("head.json"))
        finally:
            Path(temp).unlink(missing_ok=True)

    def _owned(self) -> None:
        path = self._path("global-active.lock")
        try:
            stat = path.stat()
            if (
                self._lock_bytes is None
                or self._lock_inode != (stat.st_dev, stat.st_ino)
                or path.read_bytes() != self._lock_bytes
            ):
                raise BudgetError("LOCK_OWNERSHIP_UNVERIFIED")
        except OSError as exc:
            raise BudgetError("LOCK_OWNERSHIP_UNVERIFIED") from exc

    def acquire(self) -> None:
        if self._lock_bytes is not None:
            raise BudgetError("ALREADY_ACQUIRED")
        expected_caps = self._configured()
        if any(path.is_symlink() for path in (self.root, *self.root.parents)):
            raise BudgetError("SYMLINK_STATE_REFUSED")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            raw = self._exclusive(
                "global-active.lock",
                {
                    "version": "StockOSAGYExplanationLockV1",
                    "owner": self.owner,
                    "pid": os.getpid(),
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
        except FileExistsError as exc:
            raise BudgetError("ACTIVE_OR_UNVERIFIED_LOCK") from exc
        stat = self._path("global-active.lock").stat()
        self._lock_bytes, self._lock_inode = raw, (stat.st_dev, stat.st_ino)
        try:
            policy = self._path("budget-policy.json")
            if not policy.exists():
                self._exclusive(
                    "budget-policy.json", {"version": "StockOSAGYBudgetV1", "caps": expected_caps}
                )
                self._exclusive("head.json", {"reservations": []})
            if self._read("budget-policy.json") != {
                "version": "StockOSAGYBudgetV1",
                "caps": expected_caps,
            }:
                raise BudgetError("BUDGET_POLICY_DRIFT")
            rows, records = self._state()
            recovery = self._recovery(rows, records)
            startup_repair = self._startup_repair(rows, records, recovery)
            plugin_startup_repair = self._plugin_startup_repair(
                rows, records, recovery, startup_repair
            )
            denial_protocol_repair = self._denial_protocol_repair(
                rows, records, plugin_startup_repair
            )
            self._plan_mode_repair(rows, records, denial_protocol_repair)
        except BaseException:
            self.release()
            raise

    def release(self) -> None:
        self._owned()
        self._path("global-active.lock").unlink()
        self._lock_bytes, self._lock_inode = None, None

    def _state(self) -> tuple[list[dict], list[dict]]:
        self._owned()
        expected_caps = self._configured()
        if self._read("budget-policy.json") != {
            "version": "StockOSAGYBudgetV1",
            "caps": expected_caps,
        }:
            raise BudgetError("BUDGET_POLICY_DRIFT")
        rows = self._read("head.json").get("reservations")
        if not isinstance(rows, list):
            raise BudgetError("INVALID_BUDGET_STATE")
        found = {
            path.name
            for path in self.root.glob("attempt-*.json")
            if re.fullmatch(r"attempt-\d{4,}\.json", path.name)
        }
        expected = {f"attempt-{index:04d}.json" for index in range(1, len(rows) + 1)}
        if found != expected:
            raise BudgetError("RESERVATION_JOURNAL_MISMATCH")
        records = []
        for index, row in enumerate(rows, 1):
            name = f"attempt-{index:04d}.json"
            if not isinstance(row, dict) or row.get("attempt_id") != name[:-5]:
                raise BudgetError("INVALID_BUDGET_STATE")
            raw = self._path(name).read_bytes()
            record = self._read(name)
            if (
                hashlib.sha256(raw).hexdigest() != row.get("sha256")
                or record.get("phase") not in self.caps
                or row.get("phase") != record["phase"]
                or record.get("index") != index
            ):
                raise BudgetError("RESERVATION_JOURNAL_MISMATCH")
            records.append(record)
        return rows, records

    def snapshot(self) -> dict:
        rows, records = self._state()
        recovery = self._recovery(rows, records)
        startup_repair = self._startup_repair(rows, records, recovery)
        plugin_startup_repair = self._plugin_startup_repair(rows, records, recovery, startup_repair)
        denial_protocol_repair = self._denial_protocol_repair(rows, records, plugin_startup_repair)
        plan_mode_repair = self._plan_mode_repair(rows, records, denial_protocol_repair)
        counts = {phase: sum(record["phase"] == phase for record in records) for phase in self.caps}
        return {
            "caps": dict(self.caps),
            "reserved": counts,
            "remaining": {phase: self.caps[phase] - count for phase, count in counts.items()},
            "recovery": {
                key: recovery["approval"][key]
                for key in ("attempt_id", "policy_hash", "request_sha256", "research_binding")
            }
            if recovery is not None
            else None,
            "startup_repair": {
                key: startup_repair["approval"][key]
                for key in ("attempt_id", "policy_hash", "diagnosis_sha256")
            }
            if startup_repair is not None
            else None,
            "plugin_startup_repair": {
                key: plugin_startup_repair["approval"][key]
                for key in ("attempt_id", "policy_hash", "diagnosis_sha256")
            }
            if plugin_startup_repair is not None
            else None,
            "denial_protocol_repair": {
                key: denial_protocol_repair["approval"][key]
                for key in ("attempt_id", "policy_hash", "diagnosis_sha256")
            }
            if denial_protocol_repair is not None
            else None,
            "plan_mode_repair": {
                key: plan_mode_repair["approval"][key]
                for key in ("attempt_id", "policy_hash", "diagnosis_sha256")
            }
            if plan_mode_repair is not None
            else None,
            "active_policy_hash": plan_mode_repair["approval"]["policy_hash"]
            if plan_mode_repair is not None
            else denial_protocol_repair["approval"]["policy_hash"]
            if denial_protocol_repair is not None
            else plugin_startup_repair["approval"]["policy_hash"]
            if plugin_startup_repair is not None
            else startup_repair["approval"]["policy_hash"]
            if startup_repair is not None
            else recovery["approval"]["policy_hash"]
            if recovery is not None
            else None,
        }

    def _validate_recovery_approval(
        self, approval: Any, rows: list[dict], records: list[dict]
    ) -> dict:
        """Bind one explicit decision to the retained first nonfinancial failure.

        The user decision is supplied by the trusted session controller. This is
        an evidence binding, not an identity-authentication or signature service.
        No failed bytes are rewritten or excluded from the attempt counters.
        """
        fields = {
            "version",
            "decision",
            "user_instruction",
            "policy_hash",
            "request_sha256",
            "research_binding",
            "attempt_id",
            "reservation_sha256",
            "outcome_sha256",
            "result_path",
            "result_sha256",
        }
        if (
            not isinstance(approval, dict)
            or set(approval) != fields
            or approval.get("version") != RECOVERY_APPROVAL_VERSION
            or approval.get("decision") != "APPROVED_BY_USER"
            or not isinstance(approval.get("user_instruction"), str)
            or not approval["user_instruction"].strip()
            or len(approval["user_instruction"]) > 20_000
            or approval.get("attempt_id") != RECOVERABLE_ATTEMPT
            or approval.get("request_sha256") != PINNED_REQUEST_SHA256
            or approval.get("research_binding") != PINNED_RESEARCH_BINDING
            or any(
                not isinstance(approval.get(key), str)
                or re.fullmatch(r"[0-9a-f]{64}", approval[key]) is None
                for key in (
                    "policy_hash",
                    "reservation_sha256",
                    "outcome_sha256",
                    "result_sha256",
                )
            )
        ):
            raise BudgetError("INVALID_RECOVERY_APPROVAL")
        if not rows or not records:
            raise BudgetError("RECOVERY_FAILURE_MISSING")
        row, record = rows[0], records[0]
        if (
            row["attempt_id"] != RECOVERABLE_ATTEMPT
            or record.get("index") != 1
            or record.get("phase") != "diagnostic"
            or record.get("metadata") != {"case": "connection", "synthetic_only": True}
            or approval["reservation_sha256"] != row["sha256"]
        ):
            raise BudgetError("RECOVERY_RESERVATION_MISMATCH")
        outcome_path = self._path(RECOVERABLE_ATTEMPT + ".result.json")
        if not outcome_path.is_file():
            raise BudgetError("RECOVERY_OUTCOME_MISSING")
        outcome_raw = outcome_path.read_bytes()
        outcome = self._read(outcome_path.name)
        details = outcome.get("details")
        if (
            hashlib.sha256(outcome_raw).hexdigest() != approval["outcome_sha256"]
            or outcome.get("reservation_sha256") != row["sha256"]
            or outcome.get("status") != "FAILED"
            or not isinstance(details, dict)
            or details.get("reason") != RECOVERABLE_REASON
            or details.get("result_path") != approval["result_path"]
            or details.get("result_sha256") != approval["result_sha256"]
        ):
            raise BudgetError("RECOVERY_OUTCOME_MISMATCH")
        if not isinstance(approval["result_path"], str):
            raise BudgetError("RECOVERY_RESULT_PATH_INVALID")
        result_path = Path(approval["result_path"])
        if (
            not result_path.is_absolute()
            or any(path.is_symlink() for path in (result_path, *result_path.parents))
            or not result_path.is_file()
            or result_path.stat().st_size > 2_000_000
        ):
            raise BudgetError("RECOVERY_RESULT_PATH_INVALID")
        try:
            raw = result_path.read_bytes()
            result = json.loads(raw)
        except (OSError, ValueError, RecursionError) as exc:
            raise BudgetError("RECOVERY_RESULT_INVALID") from exc
        if hashlib.sha256(raw).hexdigest() != approval["result_sha256"]:
            raise BudgetError("RECOVERY_RESULT_HASH_MISMATCH")
        if (
            not isinstance(result, dict)
            or result.get("status") != "FAIL"
            or result.get("reason") != RECOVERABLE_REASON
            or result.get("structured_output") is not None
            or result.get("owned_process_group_absent") is not True
            or type(result.get("financial_documents_sent")) is not int
            or result["financial_documents_sent"] != 0
            or type(result.get("formal_database_writes")) is not int
            or result["formal_database_writes"] != 0
            or result.get("global_settings_modified") is not False
            or type(result.get("exit_code")) is not int
            or result["exit_code"] != -9
            or result.get("actual_agent") != "stockos-evidence-reader"
            or result.get("actual_model") != "gemini-4-argon-high"
            or not isinstance(result.get("events"), list)
            or len(result["events"]) != 1
            or not isinstance(result["events"][0], dict)
            or result["events"][0].get("event") != "init"
        ):
            raise BudgetError("RECOVERY_RESULT_NOT_ELIGIBLE")
        return approval

    def _recovery(self, rows: list[dict], records: list[dict]) -> dict | None:
        """Read the immutable amendment and recheck its original evidence."""
        self._owned()
        head = self._read("head.json")
        pin = head.get("recovery_sha256")
        path = self._path(RECOVERY_FILE)
        if pin is None and not path.exists():
            return None
        if (
            not isinstance(pin, str)
            or re.fullmatch(r"[0-9a-f]{64}", pin) is None
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != pin
        ):
            raise BudgetError("RECOVERY_JOURNAL_UNVERIFIED")
        amendment = self._read(RECOVERY_FILE)
        if (
            set(amendment)
            != {
                "version",
                "approval",
                "approval_sha256",
                "caps",
                "budget_policy_sha256",
                "created_at",
            }
            or amendment.get("version") != RECOVERY_AMENDMENT_VERSION
            or amendment.get("caps") != self.caps
            or amendment.get("budget_policy_sha256")
            != hashlib.sha256(self._path("budget-policy.json").read_bytes()).hexdigest()
            or amendment.get("approval_sha256") != _sha(amendment.get("approval"))
        ):
            raise BudgetError("RECOVERY_JOURNAL_UNVERIFIED")
        self._validate_recovery_approval(amendment["approval"], rows, records)
        return amendment

    def approve_recovery(self, approval: dict) -> dict:
        """Append an explicit, policy-bound exception for only attempt-0001.

        Repeating the exact decision is idempotent; a changed decision or policy
        cannot replace it. The failure remains counted, and all later failed or
        unfinished attempts retain the ordinary stop rule.
        """
        rows, records = self._state()
        existing = self._recovery(rows, records)
        self._validate_recovery_approval(approval, rows, records)
        if existing is not None:
            if existing["approval"] != approval:
                raise BudgetError("RECOVERY_APPROVAL_CHANGED")
            return existing
        if len(rows) != 1:
            raise BudgetError("RECOVERY_MUST_PRECEDE_NEW_ATTEMPTS")
        amendment = {
            "version": RECOVERY_AMENDMENT_VERSION,
            "approval": approval,
            "approval_sha256": _sha(approval),
            "caps": dict(self.caps),
            "budget_policy_sha256": hashlib.sha256(
                self._path("budget-policy.json").read_bytes()
            ).hexdigest(),
            "created_at": datetime.now(UTC).isoformat(),
        }
        raw = self._exclusive(RECOVERY_FILE, amendment)
        self._head(rows, recovery_sha256=hashlib.sha256(raw).hexdigest())
        return amendment

    @staticmethod
    def _bound_external_json(path_value: Any, expected_sha: str) -> dict:
        if not isinstance(path_value, str):
            raise BudgetError("STARTUP_REPAIR_EVIDENCE_PATH_INVALID")
        path = Path(path_value)
        if (
            not path.is_absolute()
            or any(node.is_symlink() for node in (path, *path.parents))
            or not path.is_file()
            or path.stat().st_size > 2_000_000
        ):
            raise BudgetError("STARTUP_REPAIR_EVIDENCE_PATH_INVALID")
        try:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected_sha:
                raise BudgetError("STARTUP_REPAIR_EVIDENCE_HASH_MISMATCH")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise BudgetError("STARTUP_REPAIR_EVIDENCE_INVALID")
            return value
        except (OSError, ValueError, RecursionError) as exc:
            raise BudgetError("STARTUP_REPAIR_EVIDENCE_INVALID") from exc

    def _validate_startup_repair_approval(
        self,
        approval: Any,
        rows: list[dict],
        records: list[dict],
        recovery: dict | None,
    ) -> dict:
        fields = {
            "version",
            "decision",
            "user_instruction",
            "policy_hash",
            "request_sha256",
            "research_binding",
            "attempt_id",
            "reservation_sha256",
            "outcome_sha256",
            "result_path",
            "result_sha256",
            "diagnosis_path",
            "diagnosis_sha256",
            "prior_recovery_sha256",
        }
        if (
            not isinstance(approval, dict)
            or set(approval) != fields
            or approval.get("version") != STARTUP_REPAIR_APPROVAL_VERSION
            or approval.get("decision") != "APPROVED_BY_USER"
            or approval.get("attempt_id") != STARTUP_REPAIR_ATTEMPT
            or approval.get("request_sha256") != PINNED_REQUEST_SHA256
            or approval.get("research_binding") != PINNED_RESEARCH_BINDING
            or not isinstance(approval.get("user_instruction"), str)
            or not approval["user_instruction"].strip()
            or len(approval["user_instruction"]) > 20_000
            or any(
                not isinstance(approval.get(key), str)
                or re.fullmatch(r"[0-9a-f]{64}", approval[key]) is None
                for key in (
                    "policy_hash",
                    "reservation_sha256",
                    "outcome_sha256",
                    "result_sha256",
                    "diagnosis_sha256",
                    "prior_recovery_sha256",
                )
            )
        ):
            raise BudgetError("INVALID_STARTUP_REPAIR_APPROVAL")
        if (
            recovery is None
            or approval["prior_recovery_sha256"] != self._read("head.json").get("recovery_sha256")
            or approval["prior_recovery_sha256"]
            != hashlib.sha256(self._path(RECOVERY_FILE).read_bytes()).hexdigest()
            or approval["user_instruction"] != recovery["approval"]["user_instruction"]
            or approval["policy_hash"] == recovery["approval"]["policy_hash"]
        ):
            raise BudgetError("STARTUP_REPAIR_PRIOR_APPROVAL_MISMATCH")
        if len(rows) < 2 or len(records) < 2:
            raise BudgetError("STARTUP_REPAIR_FAILURE_MISSING")
        row, record = rows[1], records[1]
        metadata = record.get("metadata")
        if (
            row["attempt_id"] != STARTUP_REPAIR_ATTEMPT
            or record.get("index") != 2
            or record.get("phase") != "diagnostic"
            or not isinstance(metadata, dict)
            or metadata.get("stage") != "filesystem"
            or metadata.get("policy_hash") != recovery["approval"]["policy_hash"]
            or approval["reservation_sha256"] != row["sha256"]
        ):
            raise BudgetError("STARTUP_REPAIR_RESERVATION_MISMATCH")
        outcome_path = self._path(STARTUP_REPAIR_ATTEMPT + ".result.json")
        if not outcome_path.is_file():
            raise BudgetError("STARTUP_REPAIR_OUTCOME_MISSING")
        outcome = self._read(outcome_path.name)
        details = outcome.get("details")
        if (
            hashlib.sha256(outcome_path.read_bytes()).hexdigest() != approval["outcome_sha256"]
            or outcome.get("reservation_sha256") != row["sha256"]
            or outcome.get("status") != "FAILED"
            or not isinstance(details, dict)
            or details.get("reason") != "STREAM_CONTRACT_UNVERIFIED"
            or details.get("policy_hash") != recovery["approval"]["policy_hash"]
            or details.get("result_path") != approval["result_path"]
            or details.get("result_sha256") != approval["result_sha256"]
        ):
            raise BudgetError("STARTUP_REPAIR_OUTCOME_MISMATCH")
        result = self._bound_external_json(approval["result_path"], approval["result_sha256"])
        if (
            result.get("status") != "FAIL"
            or result.get("reason") != "STREAM_CONTRACT_UNVERIFIED"
            or result.get("structured_output") is not None
            or result.get("owned_process_group_absent") is not True
            or result.get("permission_mode") != "strict"
            or result.get("actual_agent") != "stockos-evidence-reader"
            or result.get("actual_model") != "gemini-4-argon-high"
            or result.get("policy_hash") != recovery["approval"]["policy_hash"]
            or type(result.get("exit_code")) is not int
            or result["exit_code"] != -9
            or result.get("hook_audit") != []
            or result.get("denied_tools") != []
            or type(result.get("financial_documents_sent")) is not int
            or result["financial_documents_sent"] != 0
            or type(result.get("formal_database_writes")) is not int
            or result["formal_database_writes"] != 0
        ):
            raise BudgetError("STARTUP_REPAIR_RESULT_NOT_ELIGIBLE")
        diagnosis = self._bound_external_json(
            approval["diagnosis_path"], approval["diagnosis_sha256"]
        )
        if (
            diagnosis.get("version") != "StockOSAGYStartupDiagnosisV1"
            or diagnosis.get("classification")
            != "EXECUTOR_CONSTRUCTION_FAILURE_BEFORE_COMPLETED_MODEL_RESPONSE"
            or diagnosis.get("conversation_id") != STARTUP_REPAIR_CONVERSATION
            or diagnosis.get("owned_workspace_confirmed") is not True
            or diagnosis.get("source_read_mode") != "ro_query_only"
            or not isinstance(diagnosis.get("steps"), list)
            or any(
                not isinstance(step, dict)
                or set(step) != {"index", "type", "status"}
                or any(type(step[key]) is not int for key in ("index", "type", "status"))
                for step in diagnosis["steps"]
            )
            or diagnosis.get("steps")
            != [
                {"index": 0, "type": 14, "status": 3},
                {"index": 1, "type": 17, "status": 3},
            ]
            or any(
                type(diagnosis.get(key)) is not int or diagnosis[key] != 0
                for key in (
                    "gen_metadata_rows",
                    "executor_metadata_rows",
                    "formal_database_writes",
                    "financial_documents_sent",
                )
            )
            or not isinstance(diagnosis.get("error_summary"), str)
            or not diagnosis["error_summary"].startswith(STARTUP_REPAIR_ERROR_PREFIX)
            or not isinstance(diagnosis.get("error_payload_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", diagnosis["error_payload_sha256"]) is None
            or diagnosis.get("inference_dispatch")
            != "NO_COMPLETED_GENERATION_METADATA_NOT_INDEPENDENT_BACKEND_ATTESTATION"
            or diagnosis.get("settings_and_hooks_restored") is not True
        ):
            raise BudgetError("STARTUP_REPAIR_DIAGNOSIS_NOT_ELIGIBLE")
        source = diagnosis.get("source_database")
        source_sha = diagnosis.get("source_database_sha256")
        if (
            not isinstance(source, str)
            or not Path(source).is_absolute()
            or Path(source).name != STARTUP_REPAIR_CONVERSATION + ".db"
            or not isinstance(source_sha, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_sha) is None
        ):
            raise BudgetError("STARTUP_REPAIR_SOURCE_FINGERPRINT_INVALID")
        # Prefer the consistent, owned read-only snapshot when provided. Keep
        # provider DB/WAL/SHM fingerprints in the pinned diagnosis rather than
        # depending on those live files remaining unchanged after housekeeping.
        snapshot = diagnosis.get("source_snapshot_path")
        snapshot_sha = diagnosis.get("source_snapshot_sha256")
        if snapshot is not None or snapshot_sha is not None:
            if (
                not isinstance(snapshot, str)
                or not Path(snapshot).is_absolute()
                or Path(snapshot).name != "owned-startup-snapshot.sqlite"
                or Path(snapshot).parent != Path(approval["diagnosis_path"]).parent
                or not isinstance(snapshot_sha, str)
                or re.fullmatch(r"[0-9a-f]{64}", snapshot_sha) is None
            ):
                raise BudgetError("STARTUP_REPAIR_SOURCE_FINGERPRINT_INVALID")
            source, source_sha = snapshot, snapshot_sha
        source_path = Path(source)
        if (
            any(node.is_symlink() for node in (source_path, *source_path.parents))
            or not source_path.is_file()
        ):
            raise BudgetError("STARTUP_REPAIR_SOURCE_FINGERPRINT_INVALID")
        with source_path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != source_sha:
                raise BudgetError("STARTUP_REPAIR_SOURCE_FINGERPRINT_CHANGED")
        return approval

    def _startup_repair(
        self,
        rows: list[dict],
        records: list[dict],
        recovery: dict | None,
    ) -> dict | None:
        self._owned()
        pin = self._read("head.json").get("startup_repair_sha256")
        path = self._path(STARTUP_REPAIR_FILE)
        if pin is None and not path.exists():
            return None
        if (
            not isinstance(pin, str)
            or re.fullmatch(r"[0-9a-f]{64}", pin) is None
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != pin
        ):
            raise BudgetError("STARTUP_REPAIR_JOURNAL_UNVERIFIED")
        amendment = self._read(STARTUP_REPAIR_FILE)
        if (
            set(amendment) != {"version", "approval", "approval_sha256", "caps", "created_at"}
            or amendment.get("version") != STARTUP_REPAIR_AMENDMENT_VERSION
            or amendment.get("caps") != self.caps
            or amendment.get("approval_sha256") != _sha(amendment.get("approval"))
        ):
            raise BudgetError("STARTUP_REPAIR_JOURNAL_UNVERIFIED")
        self._validate_startup_repair_approval(amendment["approval"], rows, records, recovery)
        return amendment

    def approve_startup_repair(self, approval: dict) -> dict:
        """Append only the bound pre-executor attempt-0002 repair, without refunds.

        This is a fixed startup exception, not a generic retry mechanism. The
        first recovery amendment and both failed outcomes remain immutable.
        """
        rows, records = self._state()
        recovery = self._recovery(rows, records)
        existing = self._startup_repair(rows, records, recovery)
        self._validate_startup_repair_approval(approval, rows, records, recovery)
        if existing is not None:
            if existing["approval"] != approval:
                raise BudgetError("STARTUP_REPAIR_APPROVAL_CHANGED")
            return existing
        if len(rows) != 2:
            raise BudgetError("STARTUP_REPAIR_MUST_PRECEDE_NEW_ATTEMPTS")
        amendment = {
            "version": STARTUP_REPAIR_AMENDMENT_VERSION,
            "approval": approval,
            "approval_sha256": _sha(approval),
            "caps": dict(self.caps),
            "created_at": datetime.now(UTC).isoformat(),
        }
        raw = self._exclusive(STARTUP_REPAIR_FILE, amendment)
        self._head(rows, startup_repair_sha256=hashlib.sha256(raw).hexdigest())
        return amendment

    def _validate_plugin_startup_repair_approval(
        self,
        approval: Any,
        rows: list[dict],
        records: list[dict],
        recovery: dict | None,
        startup_repair: dict | None,
    ) -> dict:
        """Recognize only the retained third pre-invocation plugin notice.

        This evidence binding neither authenticates the controller's user
        decision nor attests that the backend incurred no inference or cost.
        """
        fields = {
            "version",
            "decision",
            "user_instruction",
            "policy_hash",
            "request_sha256",
            "research_binding",
            "attempt_id",
            "reservation_sha256",
            "outcome_sha256",
            "result_path",
            "result_sha256",
            "diagnosis_path",
            "diagnosis_sha256",
            "prior_startup_repair_sha256",
        }
        if (
            not isinstance(approval, dict)
            or set(approval) != fields
            or approval.get("version") != PLUGIN_STARTUP_REPAIR_APPROVAL_VERSION
            or approval.get("decision") != "APPROVED_BY_USER"
            or approval.get("attempt_id") != PLUGIN_STARTUP_REPAIR_ATTEMPT
            or approval.get("request_sha256") != PINNED_REQUEST_SHA256
            or approval.get("research_binding") != PINNED_RESEARCH_BINDING
            or not isinstance(approval.get("user_instruction"), str)
            or not approval["user_instruction"].strip()
            or len(approval["user_instruction"]) > 20_000
            or any(
                not isinstance(approval.get(key), str)
                or re.fullmatch(r"[0-9a-f]{64}", approval[key]) is None
                for key in (
                    "policy_hash",
                    "reservation_sha256",
                    "outcome_sha256",
                    "result_sha256",
                    "diagnosis_sha256",
                    "prior_startup_repair_sha256",
                )
            )
        ):
            raise BudgetError("INVALID_PLUGIN_STARTUP_REPAIR_APPROVAL")
        if (
            recovery is None
            or startup_repair is None
            or approval["prior_startup_repair_sha256"]
            != self._read("head.json").get("startup_repair_sha256")
            or approval["prior_startup_repair_sha256"]
            != hashlib.sha256(self._path(STARTUP_REPAIR_FILE).read_bytes()).hexdigest()
            or approval["user_instruction"] != recovery["approval"]["user_instruction"]
            or approval["user_instruction"] != startup_repair["approval"]["user_instruction"]
            or approval["policy_hash"]
            in {recovery["approval"]["policy_hash"], startup_repair["approval"]["policy_hash"]}
        ):
            raise BudgetError("PLUGIN_STARTUP_REPAIR_PRIOR_APPROVAL_MISMATCH")
        if len(rows) < 3 or len(records) < 3:
            raise BudgetError("PLUGIN_STARTUP_REPAIR_FAILURE_MISSING")
        row, record = rows[2], records[2]
        metadata = record.get("metadata")
        prior_policy = startup_repair["approval"]["policy_hash"]
        if (
            row["attempt_id"] != PLUGIN_STARTUP_REPAIR_ATTEMPT
            or record.get("index") != 3
            or record.get("phase") != "diagnostic"
            or not isinstance(metadata, dict)
            or metadata.get("stage") != "filesystem"
            or metadata.get("policy_hash") != prior_policy
            or approval["reservation_sha256"] != row["sha256"]
        ):
            raise BudgetError("PLUGIN_STARTUP_REPAIR_RESERVATION_MISMATCH")
        outcome_path = self._path(PLUGIN_STARTUP_REPAIR_ATTEMPT + ".result.json")
        if not outcome_path.is_file():
            raise BudgetError("PLUGIN_STARTUP_REPAIR_OUTCOME_MISSING")
        outcome = self._read(outcome_path.name)
        details = outcome.get("details")
        if (
            hashlib.sha256(outcome_path.read_bytes()).hexdigest() != approval["outcome_sha256"]
            or outcome.get("reservation_sha256") != row["sha256"]
            or outcome.get("status") != "FAILED"
            or not isinstance(details, dict)
            or details.get("reason") != "STREAM_CONTRACT_UNVERIFIED"
            or details.get("policy_hash") != prior_policy
            or details.get("result_path") != approval["result_path"]
            or details.get("result_sha256") != approval["result_sha256"]
        ):
            raise BudgetError("PLUGIN_STARTUP_REPAIR_OUTCOME_MISMATCH")
        result = self._bound_external_json(approval["result_path"], approval["result_sha256"])
        audit = result.get("hook_audit")
        stream = result.get("stream_events")
        if (
            result.get("status") != "FAIL"
            or result.get("reason") != "STREAM_CONTRACT_UNVERIFIED"
            or result.get("structured_output") is not None
            or result.get("owned_process_group_absent") is not True
            or result.get("permission_mode") != "strict"
            or result.get("actual_agent") != "stockos-evidence-reader"
            or result.get("actual_model") != "gemini-4-argon-high"
            or result.get("policy_hash") != prior_policy
            or type(result.get("exit_code")) is not int
            or result["exit_code"] != -9
            or result.get("denied_tools") != []
            or result.get("tool_completion_metadata") != []
            or any(
                type(result.get(key)) is not int or result[key] != 0
                for key in ("financial_documents_sent", "formal_database_writes")
            )
            or not isinstance(audit, list)
            or len(audit) != 1
            or not isinstance(audit[0], dict)
            or audit[0].get("event") != "session"
            or audit[0].get("configuration_matches") is not True
            or audit[0].get("conversation_id") != PLUGIN_STARTUP_REPAIR_CONVERSATION
            or audit[0].get("model_name") != "gemini-4-argon-high"
            or not isinstance(audit[0].get("nonce"), str)
            or re.fullmatch(r"[0-9a-f]{32}", audit[0]["nonce"]) is None
            or not isinstance(audit[0].get("workspaces"), list)
            or len(audit[0]["workspaces"]) != 1
            or not isinstance(audit[0]["workspaces"][0], str)
            or not Path(audit[0]["workspaces"][0]).is_absolute()
            or any(
                audit[0].get(key) is not None
                for key in ("invocation_number", "step_index", "tool_name")
            )
            or not isinstance(stream, list)
            or len(stream) != 3
            or any(not isinstance(event, dict) for event in stream)
            or stream[0].get("event") != "init"
            or not isinstance(stream[0].get("init"), dict)
            or stream[0]["init"].get("agent") != "stockos-evidence-reader"
            or stream[0]["init"].get("model") != "gemini-4-argon-high"
            or stream[0]["init"].get("permission_mode") != "strict"
            or any(
                event.get("event") != "step_update"
                or event.get("step_state") != "DONE"
                or event.get("step_type") != step_type
                or event.get("tool_events") != []
                for event, step_type in zip(stream[1:], ("user_input", "unknown"), strict=True)
            )
        ):
            raise BudgetError("PLUGIN_STARTUP_REPAIR_RESULT_NOT_ELIGIBLE")
        diagnosis = self._bound_external_json(
            approval["diagnosis_path"], approval["diagnosis_sha256"]
        )
        if (
            diagnosis.get("version") != "StockOSAGYPluginStartupDiagnosisV1"
            or diagnosis.get("classification")
            != "PLUGIN_INITIALIZATION_NOTICE_BEFORE_PRE_INVOCATION"
            or diagnosis.get("conversation_id") != PLUGIN_STARTUP_REPAIR_CONVERSATION
            or diagnosis.get("owned_workspace_confirmed") is not True
            or diagnosis.get("source_read_mode") != "ro_query_only"
            or not isinstance(diagnosis.get("steps"), list)
            or any(
                not isinstance(step, dict)
                or set(step) != {"index", "type", "status"}
                or any(type(step[key]) is not int for key in ("index", "type", "status"))
                for step in diagnosis["steps"]
            )
            or diagnosis["steps"]
            != [{"index": 0, "type": 14, "status": 3}, {"index": 1, "type": 90, "status": 3}]
            or diagnosis.get("installed_binary_enum_type_90")
            != "CORTEX_STEP_TYPE_EPHEMERAL_MESSAGE"
            or diagnosis.get("notice_summary") != PLUGIN_STARTUP_NOTICE
            or diagnosis.get("error_payload_sha256") != PLUGIN_STARTUP_PAYLOAD_SHA256
            or diagnosis.get("session_hook_loaded") is not True
            or diagnosis.get("pre_invocation_observed") is not False
            or any(
                type(diagnosis.get(key)) is not int or diagnosis[key] != 0
                for key in (
                    "gen_metadata_rows",
                    "executor_metadata_rows",
                    "formal_database_writes",
                    "financial_documents_sent",
                )
            )
            or diagnosis.get("inference_dispatch")
            != "NO_COMPLETED_GENERATION_METADATA_NOT_INDEPENDENT_BACKEND_ATTESTATION"
            or diagnosis.get("settings_and_hooks_restored") is not True
        ):
            raise BudgetError("PLUGIN_STARTUP_REPAIR_DIAGNOSIS_NOT_ELIGIBLE")
        source = diagnosis.get("source_database")
        snapshot = diagnosis.get("source_snapshot_path")
        snapshot_sha = diagnosis.get("source_snapshot_sha256")
        if (
            not isinstance(source, str)
            or not Path(source).is_absolute()
            or Path(source).name != PLUGIN_STARTUP_REPAIR_CONVERSATION + ".db"
            or not isinstance(snapshot, str)
            or not Path(snapshot).is_absolute()
            or Path(snapshot).name != "owned-startup-snapshot.sqlite"
            or Path(snapshot).parent != Path(approval["diagnosis_path"]).parent
            or not isinstance(snapshot_sha, str)
            or re.fullmatch(r"[0-9a-f]{64}", snapshot_sha) is None
        ):
            raise BudgetError("PLUGIN_STARTUP_REPAIR_SOURCE_FINGERPRINT_INVALID")
        snapshot_path = Path(snapshot)
        if (
            any(node.is_symlink() for node in (snapshot_path, *snapshot_path.parents))
            or not snapshot_path.is_file()
        ):
            raise BudgetError("PLUGIN_STARTUP_REPAIR_SOURCE_FINGERPRINT_INVALID")
        with snapshot_path.open("rb") as source_stream:
            if hashlib.file_digest(source_stream, "sha256").hexdigest() != snapshot_sha:
                raise BudgetError("PLUGIN_STARTUP_REPAIR_SOURCE_FINGERPRINT_CHANGED")
        return approval

    def _plugin_startup_repair(
        self,
        rows: list[dict],
        records: list[dict],
        recovery: dict | None,
        startup_repair: dict | None,
    ) -> dict | None:
        self._owned()
        pin = self._read("head.json").get("plugin_startup_repair_sha256")
        path = self._path(PLUGIN_STARTUP_REPAIR_FILE)
        if pin is None and not path.exists():
            return None
        if (
            not isinstance(pin, str)
            or re.fullmatch(r"[0-9a-f]{64}", pin) is None
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != pin
        ):
            raise BudgetError("PLUGIN_STARTUP_REPAIR_JOURNAL_UNVERIFIED")
        amendment = self._read(PLUGIN_STARTUP_REPAIR_FILE)
        if (
            set(amendment) != {"version", "approval", "approval_sha256", "caps", "created_at"}
            or amendment.get("version") != PLUGIN_STARTUP_REPAIR_AMENDMENT_VERSION
            or amendment.get("caps") != self.caps
            or amendment.get("approval_sha256") != _sha(amendment.get("approval"))
        ):
            raise BudgetError("PLUGIN_STARTUP_REPAIR_JOURNAL_UNVERIFIED")
        self._validate_plugin_startup_repair_approval(
            amendment["approval"], rows, records, recovery, startup_repair
        )
        return amendment

    def approve_plugin_startup_repair(self, approval: dict) -> dict:
        """Append only the exact third plugin startup exception; retain all caps/failures."""
        rows, records = self._state()
        recovery = self._recovery(rows, records)
        startup_repair = self._startup_repair(rows, records, recovery)
        existing = self._plugin_startup_repair(rows, records, recovery, startup_repair)
        self._validate_plugin_startup_repair_approval(
            approval, rows, records, recovery, startup_repair
        )
        if existing is not None:
            if existing["approval"] != approval:
                raise BudgetError("PLUGIN_STARTUP_REPAIR_APPROVAL_CHANGED")
            return existing
        if len(rows) != 3:
            raise BudgetError("PLUGIN_STARTUP_REPAIR_MUST_PRECEDE_NEW_ATTEMPTS")
        amendment = {
            "version": PLUGIN_STARTUP_REPAIR_AMENDMENT_VERSION,
            "approval": approval,
            "approval_sha256": _sha(approval),
            "caps": dict(self.caps),
            "created_at": datetime.now(UTC).isoformat(),
        }
        raw = self._exclusive(PLUGIN_STARTUP_REPAIR_FILE, amendment)
        self._head(rows, plugin_startup_repair_sha256=hashlib.sha256(raw).hexdigest())
        return amendment

    def _validate_denial_protocol_repair_approval(
        self,
        approval: Any,
        rows: list[dict],
        records: list[dict],
        plugin_startup_repair: dict | None,
    ) -> dict:
        """Bind only attempt-0004's synthetic denial/parser mismatch, not a retry.

        Its single completed synthetic generation remains explicitly counted in
        the diagnosis. This exception makes no zero-inference or quality claim.
        """
        fields = {
            "version",
            "decision",
            "user_instruction",
            "policy_hash",
            "request_sha256",
            "research_binding",
            "attempt_id",
            "reservation_sha256",
            "outcome_sha256",
            "result_path",
            "result_sha256",
            "diagnosis_path",
            "diagnosis_sha256",
            "prior_plugin_startup_repair_sha256",
        }
        if (
            not isinstance(approval, dict)
            or set(approval) != fields
            or approval.get("version") != DENIAL_PROTOCOL_REPAIR_APPROVAL_VERSION
            or approval.get("decision") != "APPROVED_BY_USER"
            or approval.get("attempt_id") != DENIAL_PROTOCOL_REPAIR_ATTEMPT
            or approval.get("request_sha256") != PINNED_REQUEST_SHA256
            or approval.get("research_binding") != PINNED_RESEARCH_BINDING
            or not isinstance(approval.get("user_instruction"), str)
            or not approval["user_instruction"].strip()
            or len(approval["user_instruction"]) > 20_000
            or any(
                not isinstance(approval.get(key), str)
                or re.fullmatch(r"[0-9a-f]{64}", approval[key]) is None
                for key in (
                    "policy_hash",
                    "reservation_sha256",
                    "outcome_sha256",
                    "result_sha256",
                    "diagnosis_sha256",
                    "prior_plugin_startup_repair_sha256",
                )
            )
        ):
            raise BudgetError("INVALID_DENIAL_PROTOCOL_REPAIR_APPROVAL")
        if (
            plugin_startup_repair is None
            or approval["prior_plugin_startup_repair_sha256"]
            != self._read("head.json").get("plugin_startup_repair_sha256")
            or approval["prior_plugin_startup_repair_sha256"]
            != hashlib.sha256(self._path(PLUGIN_STARTUP_REPAIR_FILE).read_bytes()).hexdigest()
            or approval["user_instruction"] != plugin_startup_repair["approval"]["user_instruction"]
            or approval["policy_hash"]
            in {
                self._read(name)["approval"]["policy_hash"]
                for name in (RECOVERY_FILE, STARTUP_REPAIR_FILE, PLUGIN_STARTUP_REPAIR_FILE)
            }
        ):
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_PRIOR_APPROVAL_MISMATCH")
        if len(rows) < 4 or len(records) < 4:
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_FAILURE_MISSING")
        prior_policy = plugin_startup_repair["approval"]["policy_hash"]
        row, record = rows[3], records[3]
        metadata = record.get("metadata")
        if (
            row["attempt_id"] != DENIAL_PROTOCOL_REPAIR_ATTEMPT
            or record.get("index") != 4
            or record.get("phase") != "diagnostic"
            or not isinstance(metadata, dict)
            or metadata.get("stage") != "filesystem_command_and_write"
            or metadata.get("policy_hash") != prior_policy
            or approval["reservation_sha256"] != row["sha256"]
        ):
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_RESERVATION_MISMATCH")
        outcome_path = self._path(DENIAL_PROTOCOL_REPAIR_ATTEMPT + ".result.json")
        if not outcome_path.is_file():
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_OUTCOME_MISSING")
        outcome = self._read(outcome_path.name)
        details = outcome.get("details")
        if (
            hashlib.sha256(outcome_path.read_bytes()).hexdigest() != approval["outcome_sha256"]
            or outcome.get("reservation_sha256") != row["sha256"]
            or outcome.get("status") != "FAILED"
            or not isinstance(details, dict)
            or details.get("reason") != "STREAM_CONTRACT_UNVERIFIED"
            or details.get("policy_hash") != prior_policy
            or details.get("result_path") != approval["result_path"]
            or details.get("result_sha256") != approval["result_sha256"]
        ):
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_OUTCOME_MISMATCH")
        result = self._bound_external_json(approval["result_path"], approval["result_sha256"])
        audit = result.get("hook_audit")
        stream = result.get("stream_events")
        if (
            result.get("status") != "FAIL"
            or result.get("reason") != "STREAM_CONTRACT_UNVERIFIED"
            or result.get("structured_output") is not None
            or result.get("owned_process_group_absent") is not True
            or result.get("permission_mode") != "strict"
            or result.get("actual_agent") != "stockos-evidence-reader"
            or result.get("actual_model") != "gemini-4-argon-high"
            or result.get("policy_hash") != prior_policy
            or type(result.get("exit_code")) is not int
            or result["exit_code"] != -9
            or result.get("denied_tools") != []
            or result.get("tool_completion_metadata") != []
            or any(
                type(result.get(key)) is not int or result[key] != 0
                for key in ("financial_documents_sent", "formal_database_writes")
            )
            or not isinstance(audit, list)
            or len(audit) != 3
            or any(not isinstance(event, dict) for event in audit)
            or [event.get("event") for event in audit] != ["session", "invocation", "pre"]
            or not isinstance(audit[0].get("nonce"), str)
            or re.fullmatch(r"[0-9a-f]{32}", audit[0]["nonce"]) is None
            or not isinstance(audit[0].get("workspaces"), list)
            or len(audit[0]["workspaces"]) != 1
            or not isinstance(audit[0]["workspaces"][0], str)
            or not Path(audit[0]["workspaces"][0]).is_absolute()
            or any(
                event.get("configuration_matches") is not True
                or event.get("conversation_id") != DENIAL_PROTOCOL_REPAIR_CONVERSATION
                or event.get("model_name") != "gemini-4-argon-high"
                or event.get("nonce") != audit[0]["nonce"]
                or event.get("workspaces") != audit[0]["workspaces"]
                for event in audit
            )
            or any(
                audit[0].get(key) is not None
                for key in ("invocation_number", "step_index", "tool_name")
            )
            or type(audit[1].get("invocation_number")) is not int
            or audit[1]["invocation_number"] != 0
            or audit[1].get("blocked") is not False
            or any(audit[1].get(key) is not None for key in ("step_index", "tool_name"))
            or audit[2].get("decision") != "deny"
            or audit[2].get("tool_name") != "view_file"
            or type(audit[2].get("step_index")) is not int
            or audit[2]["step_index"] != 2
            or audit[2].get("args_sha256") != DENIAL_PROTOCOL_ARGS_SHA256
            or audit[2].get("invocation_number") is not None
            or not isinstance(stream, list)
            or len(stream) != 5
            or any(not isinstance(event, dict) for event in stream)
            or stream[0].get("event") != "init"
            or not isinstance(stream[0].get("init"), dict)
            or stream[0]["init"].get("agent") != "stockos-evidence-reader"
            or stream[0]["init"].get("model") != "gemini-4-argon-high"
            or stream[0]["init"].get("permission_mode") != "strict"
            or any(
                event.get("event") != "step_update"
                or event.get("step_state") != state
                or event.get("step_type") != step_type
                or event.get("tool_events") != tool_events
                for event, (state, step_type, tool_events) in zip(
                    stream[1:],
                    (
                        ("DONE", "user_input", []),
                        ("DONE", "agent_response", []),
                        ("ACTIVE", "tool", [{"state": "ACTIVE", "tool_name": "view_file"}]),
                        ("ERROR", "tool", [{"state": "ERROR", "tool_name": "view_file"}]),
                    ),
                    strict=True,
                )
            )
        ):
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_RESULT_NOT_ELIGIBLE")
        diagnosis = self._bound_external_json(
            approval["diagnosis_path"], approval["diagnosis_sha256"]
        )
        if (
            diagnosis.get("version") != "StockOSAGYDenialProtocolDiagnosisV1"
            or diagnosis.get("classification")
            != "PINNED_PRE_TOOL_DENIAL_ERROR_STATE_REJECTED_BY_ADAPTER"
            or diagnosis.get("conversation_id") != DENIAL_PROTOCOL_REPAIR_CONVERSATION
            or diagnosis.get("owned_workspace_confirmed") is not True
            or diagnosis.get("source_read_mode") != "ro_query_only"
            or not isinstance(diagnosis.get("steps"), list)
            or any(
                not isinstance(step, dict)
                or set(step) != {"index", "type", "status"}
                or any(type(step[key]) is not int for key in ("index", "type", "status"))
                for step in diagnosis["steps"]
            )
            or diagnosis["steps"]
            != [
                {"index": 0, "type": 14, "status": 3},
                {"index": 1, "type": 15, "status": 3},
                {"index": 2, "type": 132, "status": 7},
                {"index": 3, "type": 132, "status": 2},
                {"index": 4, "type": 132, "status": 1},
            ]
            or type(diagnosis.get("gen_metadata_rows")) is not int
            or diagnosis["gen_metadata_rows"] != 1
            or diagnosis.get("inference_scope")
            != "ONE_COMPLETED_SYNTHETIC_GENERATION; NO_FINANCIAL_DOCUMENTS"
            or any(
                type(diagnosis.get(key)) is not int or diagnosis[key] != 0
                for key in (
                    "executor_metadata_rows",
                    "formal_database_writes",
                    "financial_documents_sent",
                )
            )
            or diagnosis.get("blocked_tool_name") != "view_file"
            or type(diagnosis.get("blocked_step_index")) is not int
            or diagnosis["blocked_step_index"] != 2
            or diagnosis.get("blocked_args_sha256") != DENIAL_PROTOCOL_ARGS_SHA256
            or diagnosis.get("error_details_sha256") != DENIAL_PROTOCOL_ERROR_SHA256
            or diagnosis.get("denial_message") != DENIAL_PROTOCOL_MESSAGE
            or diagnosis.get("settings_hooks_plugins_restored") is not True
            or diagnosis.get("pre_invocation_observed") is not True
            or diagnosis.get("post_tool_hook_observed") is not False
            or diagnosis.get("stream_terminal_state") != "ERROR"
        ):
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_DIAGNOSIS_NOT_ELIGIBLE")
        source = diagnosis.get("source_database")
        snapshot = diagnosis.get("source_snapshot_path")
        snapshot_sha = diagnosis.get("source_snapshot_sha256")
        if (
            not isinstance(source, str)
            or not Path(source).is_absolute()
            or Path(source).name != DENIAL_PROTOCOL_REPAIR_CONVERSATION + ".db"
            or not isinstance(snapshot, str)
            or not Path(snapshot).is_absolute()
            or Path(snapshot).name != "owned-protocol-snapshot.sqlite"
            or Path(snapshot).parent != Path(approval["diagnosis_path"]).parent
            or not isinstance(snapshot_sha, str)
            or re.fullmatch(r"[0-9a-f]{64}", snapshot_sha) is None
        ):
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_SOURCE_FINGERPRINT_INVALID")
        snapshot_path = Path(snapshot)
        if (
            any(node.is_symlink() for node in (snapshot_path, *snapshot_path.parents))
            or not snapshot_path.is_file()
        ):
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_SOURCE_FINGERPRINT_INVALID")
        with snapshot_path.open("rb") as source_stream:
            if hashlib.file_digest(source_stream, "sha256").hexdigest() != snapshot_sha:
                raise BudgetError("DENIAL_PROTOCOL_REPAIR_SOURCE_FINGERPRINT_CHANGED")
        return approval

    def _denial_protocol_repair(
        self, rows: list[dict], records: list[dict], plugin_startup_repair: dict | None
    ) -> dict | None:
        self._owned()
        pin = self._read("head.json").get("denial_protocol_repair_sha256")
        path = self._path(DENIAL_PROTOCOL_REPAIR_FILE)
        if pin is None and not path.exists():
            return None
        if (
            not isinstance(pin, str)
            or re.fullmatch(r"[0-9a-f]{64}", pin) is None
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != pin
        ):
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_JOURNAL_UNVERIFIED")
        amendment = self._read(DENIAL_PROTOCOL_REPAIR_FILE)
        if (
            set(amendment) != {"version", "approval", "approval_sha256", "caps", "created_at"}
            or amendment.get("version") != DENIAL_PROTOCOL_REPAIR_AMENDMENT_VERSION
            or amendment.get("caps") != self.caps
            or amendment.get("approval_sha256") != _sha(amendment.get("approval"))
        ):
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_JOURNAL_UNVERIFIED")
        self._validate_denial_protocol_repair_approval(
            amendment["approval"], rows, records, plugin_startup_repair
        )
        return amendment

    def approve_denial_protocol_repair(self, approval: dict) -> dict:
        """Append only attempt-0004's known synthetic adapter repair, without refunds."""
        rows, records = self._state()
        recovery = self._recovery(rows, records)
        startup_repair = self._startup_repair(rows, records, recovery)
        plugin_startup_repair = self._plugin_startup_repair(rows, records, recovery, startup_repair)
        existing = self._denial_protocol_repair(rows, records, plugin_startup_repair)
        self._validate_denial_protocol_repair_approval(
            approval, rows, records, plugin_startup_repair
        )
        if existing is not None:
            if existing["approval"] != approval:
                raise BudgetError("DENIAL_PROTOCOL_REPAIR_APPROVAL_CHANGED")
            return existing
        if len(rows) != 4:
            raise BudgetError("DENIAL_PROTOCOL_REPAIR_MUST_PRECEDE_NEW_ATTEMPTS")
        amendment = {
            "version": DENIAL_PROTOCOL_REPAIR_AMENDMENT_VERSION,
            "approval": approval,
            "approval_sha256": _sha(approval),
            "caps": dict(self.caps),
            "created_at": datetime.now(UTC).isoformat(),
        }
        raw = self._exclusive(DENIAL_PROTOCOL_REPAIR_FILE, amendment)
        self._head(rows, denial_protocol_repair_sha256=hashlib.sha256(raw).hexdigest())
        return amendment

    def _validate_plan_mode_repair_approval(
        self,
        approval: Any,
        rows: list[dict],
        records: list[dict],
        denial_protocol_repair: dict | None,
    ) -> dict:
        """Recognize only the fifth synthetic mode/protocol correction.

        Five synthetic generations and one executor are retained as observed.
        Missing structured output remains failure; raw JSON is never admitted.
        The observed partial denials do not qualify a subsequent research run.
        """
        fields = {
            "version",
            "decision",
            "user_instruction",
            "policy_hash",
            "request_sha256",
            "research_binding",
            "attempt_id",
            "reservation_sha256",
            "outcome_sha256",
            "result_path",
            "result_sha256",
            "diagnosis_path",
            "diagnosis_sha256",
            "prior_denial_protocol_repair_sha256",
        }
        if (
            not isinstance(approval, dict)
            or set(approval) != fields
            or approval.get("version") != PLAN_MODE_REPAIR_APPROVAL_VERSION
            or approval.get("decision") != "APPROVED_BY_USER"
            or approval.get("attempt_id") != PLAN_MODE_REPAIR_ATTEMPT
            or approval.get("request_sha256") != PINNED_REQUEST_SHA256
            or approval.get("research_binding") != PINNED_RESEARCH_BINDING
            or not isinstance(approval.get("user_instruction"), str)
            or not approval["user_instruction"].strip()
            or len(approval["user_instruction"]) > 20_000
            or any(
                not isinstance(approval.get(key), str)
                or re.fullmatch(r"[0-9a-f]{64}", approval[key]) is None
                for key in (
                    "policy_hash",
                    "reservation_sha256",
                    "outcome_sha256",
                    "result_sha256",
                    "diagnosis_sha256",
                    "prior_denial_protocol_repair_sha256",
                )
            )
        ):
            raise BudgetError("INVALID_PLAN_MODE_REPAIR_APPROVAL")
        if (
            denial_protocol_repair is None
            or approval["prior_denial_protocol_repair_sha256"]
            != self._read("head.json").get("denial_protocol_repair_sha256")
            or approval["prior_denial_protocol_repair_sha256"]
            != hashlib.sha256(self._path(DENIAL_PROTOCOL_REPAIR_FILE).read_bytes()).hexdigest()
            or approval["user_instruction"]
            != denial_protocol_repair["approval"]["user_instruction"]
            or approval["policy_hash"]
            in {
                self._read(name)["approval"]["policy_hash"]
                for name in (
                    RECOVERY_FILE,
                    STARTUP_REPAIR_FILE,
                    PLUGIN_STARTUP_REPAIR_FILE,
                    DENIAL_PROTOCOL_REPAIR_FILE,
                )
            }
        ):
            raise BudgetError("PLAN_MODE_REPAIR_PRIOR_APPROVAL_MISMATCH")
        if len(rows) < 5 or len(records) < 5:
            raise BudgetError("PLAN_MODE_REPAIR_FAILURE_MISSING")
        prior = denial_protocol_repair["approval"]
        row, record = rows[4], records[4]
        metadata = record.get("metadata")
        if (
            row["attempt_id"] != PLAN_MODE_REPAIR_ATTEMPT
            or record.get("index") != 5
            or record.get("phase") != "diagnostic"
            or not isinstance(metadata, dict)
            or metadata.get("stage") != "filesystem_command_write_url_and_search"
            or metadata.get("policy_hash") != prior["policy_hash"]
            or approval["reservation_sha256"] != row["sha256"]
        ):
            raise BudgetError("PLAN_MODE_REPAIR_RESERVATION_MISMATCH")
        outcome_path = self._path(PLAN_MODE_REPAIR_ATTEMPT + ".result.json")
        if not outcome_path.is_file():
            raise BudgetError("PLAN_MODE_REPAIR_OUTCOME_MISSING")
        outcome = self._read(outcome_path.name)
        details = outcome.get("details")
        if (
            hashlib.sha256(outcome_path.read_bytes()).hexdigest() != approval["outcome_sha256"]
            or outcome.get("reservation_sha256") != row["sha256"]
            or outcome.get("status") != "FAILED"
            or not isinstance(details, dict)
            or details.get("reason") != "PROVIDER_OR_SCHEMA_FAILURE"
            or details.get("policy_hash") != prior["policy_hash"]
            or details.get("result_path") != approval["result_path"]
            or details.get("result_sha256") != approval["result_sha256"]
        ):
            raise BudgetError("PLAN_MODE_REPAIR_OUTCOME_MISMATCH")
        result = self._bound_external_json(approval["result_path"], approval["result_sha256"])
        audit = result.get("hook_audit")
        stream = result.get("stream_events")
        completions = result.get("tool_completion_metadata")
        expected_audit = [
            "session",
            "invocation",
            *(["pre"] * 5),
            "postinvocation",
            *(["invocation", "postinvocation"] * 4),
            "stop",
        ]
        if (
            result.get("status") != "FAIL"
            or result.get("reason") != "PROVIDER_OR_SCHEMA_FAILURE"
            or result.get("structured_output") is not None
            or result.get("owned_process_group_absent") is not True
            or result.get("permission_mode") != "strict"
            or result.get("actual_agent") != "stockos-evidence-reader"
            or result.get("actual_model") != "gemini-4-argon-high"
            or result.get("policy_hash") != prior["policy_hash"]
            or type(result.get("exit_code")) is not int
            or result["exit_code"] != 0
            or result.get("denied_tools") != []
            or any(
                type(result.get(key)) is not int or result[key] != 0
                for key in ("financial_documents_sent", "formal_database_writes")
            )
            or not isinstance(audit, list)
            or len(audit) != len(expected_audit)
            or any(not isinstance(event, dict) for event in audit)
            or [event.get("event") for event in audit] != expected_audit
            or not isinstance(audit[0].get("nonce"), str)
            or re.fullmatch(r"[0-9a-f]{32}", audit[0]["nonce"]) is None
            or not isinstance(audit[0].get("workspaces"), list)
            or len(audit[0]["workspaces"]) != 1
            or not isinstance(audit[0]["workspaces"][0], str)
            or not Path(audit[0]["workspaces"][0]).is_absolute()
            or any(
                event.get("configuration_matches") is not True
                or event.get("conversation_id") != PLAN_MODE_REPAIR_CONVERSATION
                or event.get("model_name") != "gemini-4-argon-high"
                or event.get("nonce") != audit[0]["nonce"]
                or event.get("workspaces") != audit[0]["workspaces"]
                for event in audit
            )
            or not isinstance(completions, list)
            or len(completions) != 5
            or any(not isinstance(event, dict) for event in completions)
            or not isinstance(stream, list)
            or len(stream) < 2
            or any(not isinstance(event, dict) for event in stream)
            or stream[0].get("event") != "init"
            or not isinstance(stream[0].get("init"), dict)
            or stream[0]["init"].get("agent") != "stockos-evidence-reader"
            or stream[0]["init"].get("model") != "gemini-4-argon-high"
            or stream[0]["init"].get("permission_mode") != "strict"
            or stream[-1].get("event") != "result"
            or stream[-1].get("result_status") != "SUCCESS"
            or any(
                event.get("event") != "step_update"
                or event.get("step_type") not in {"user_input", "agent_response", "tool"}
                or event.get("step_state")
                not in (
                    {"ACTIVE", "ERROR"} if event.get("step_type") == "tool" else {"ACTIVE", "DONE"}
                )
                or (event.get("step_type") != "tool" and event.get("tool_events") != [])
                for event in stream[1:-1]
            )
            or sum(
                event.get("step_type") == "agent_response" and event.get("step_state") == "DONE"
                for event in stream
            )
            != 5
            or sum(
                event.get("step_type") == "user_input" and event.get("step_state") == "DONE"
                for event in stream
            )
            != 4
        ):
            raise BudgetError("PLAN_MODE_REPAIR_RESULT_NOT_ELIGIBLE")
        for kind in ("invocation", "postinvocation"):
            calls = [event for event in audit if event["event"] == kind]
            if any(type(event.get("invocation_number")) is not int for event in calls) or [
                event["invocation_number"] for event in calls
            ] != list(range(5)):
                raise BudgetError("PLAN_MODE_REPAIR_INVOCATIONS_NOT_ELIGIBLE")
            if kind == "invocation" and any(event.get("blocked") is not False for event in calls):
                raise BudgetError("PLAN_MODE_REPAIR_INVOCATIONS_NOT_ELIGIBLE")
        if (
            any(
                event.get("step_index") is not None
                or event.get("tool_name") is not None
                or event.get("args_sha256") != hashlib.sha256(b"{}").hexdigest()
                or (
                    event["event"] in {"session", "stop"}
                    and event.get("invocation_number") is not None
                )
                for event in audit
                if event["event"] != "pre"
            )
            or audit[-1].get("fully_idle") is not True
            or audit[-1].get("termination_reason") != "MAX_FORCED_INVOCATIONS"
        ):
            raise BudgetError("PLAN_MODE_REPAIR_INVOCATIONS_NOT_ELIGIBLE")
        prior_diagnosis = self._bound_external_json(
            prior["diagnosis_path"], prior["diagnosis_sha256"]
        )
        for event, completion, (name, index, args_sha) in zip(
            audit[2:7], completions, PLAN_MODE_DENIALS, strict=True
        ):
            if (
                event.get("decision") != "deny"
                or event.get("tool_name") != name
                or type(event.get("step_index")) is not int
                or event["step_index"] != index
                or event.get("args_sha256") != args_sha
                or event.get("invocation_number") is not None
                or completion.get("tool_name") != name
                or completion.get("conversation_id") != PLAN_MODE_REPAIR_CONVERSATION
                or type(completion.get("step_index")) is not int
                or completion["step_index"] != index
                or completion.get("args_sha256") != args_sha
                or completion.get("state") != "ERROR"
                or completion.get("error_message_sha256")
                != hashlib.sha256(DENIAL_PROTOCOL_MESSAGE.encode()).hexdigest()
                or type(completion.get("error_message_characters")) is not int
                or completion["error_message_characters"] != len(DENIAL_PROTOCOL_MESSAGE)
                or any(
                    completion.get(key) is not True
                    for key in (
                        "error_shape_valid",
                        "exact_pre_tool_denial",
                        "installed_binary_message_prefix",
                        "output_empty",
                    )
                )
                or completion.get("output_type") != "NoneType"
                or completion.get("error_type_authority") != "SHAPE_ONLY_NOT_PERMISSION_ENUM"
                or completion.get("stream_denial_contract")
                != "PINNED_CLI_ERROR_AND_TRUSTED_PRE_REQUIRED"
                or completion.get("protocol_diagnosis_sha256") != prior["diagnosis_sha256"]
                or completion.get("protocol_snapshot_sha256")
                != prior_diagnosis["source_snapshot_sha256"]
            ):
                raise BudgetError("PLAN_MODE_REPAIR_DENIALS_NOT_ELIGIBLE")
        tool_stream = [event for event in stream if event.get("step_type") == "tool"]
        expected_tools = [
            (name, state) for name, _, _ in PLAN_MODE_DENIALS for state in ("ACTIVE", "ERROR")
        ]
        if len(tool_stream) != len(expected_tools) or any(
            event.get("step_state") != state
            or event.get("tool_events") != [{"state": state, "tool_name": name}]
            for event, (name, state) in zip(tool_stream, expected_tools, strict=True)
        ):
            raise BudgetError("PLAN_MODE_REPAIR_DENIALS_NOT_ELIGIBLE")
        diagnosis = self._bound_external_json(
            approval["diagnosis_path"], approval["diagnosis_sha256"]
        )
        expected_steps = [
            (0, 14, 3),
            (1, 15, 3),
            *[(i, 132, 7) for i in range(2, 7)],
            (7, 15, 3),
            (8, 14, 3),
            (9, 15, 3),
            (10, 14, 3),
            (11, 15, 3),
            (12, 14, 3),
            (13, 15, 3),
        ]
        if (
            diagnosis.get("version") != "StockOSAGYPlanModeDiagnosisV1"
            or diagnosis.get("classification")
            != "SYNTHETIC_PLAN_MODE_WITH_NO_ADMITTED_STRUCTURED_OBJECT"
            or diagnosis.get("conversation_id") != PLAN_MODE_REPAIR_CONVERSATION
            or diagnosis.get("owned_workspace_confirmed") is not True
            or diagnosis.get("source_read_mode") != "ro_immutable_query_only_no_sidecars"
            or not isinstance(diagnosis.get("steps"), list)
            or any(
                not isinstance(step, dict)
                or set(step) != {"index", "type", "status"}
                or any(type(step[key]) is not int for key in ("index", "type", "status"))
                for step in diagnosis["steps"]
            )
            or diagnosis["steps"]
            != [{"index": i, "type": t, "status": s} for i, t, s in expected_steps]
            or any(
                type(diagnosis.get(key)) is not int or diagnosis[key] != value
                for key, value in (
                    ("gen_metadata_rows", 5),
                    ("executor_metadata_rows", 1),
                    ("terminal_exit_code", 0),
                    ("observed_denied_count", 5),
                    ("formal_database_writes", 0),
                    ("financial_documents_sent", 0),
                )
            )
            or diagnosis.get("synthetic_model_responses_present") is not True
            or diagnosis.get("terminal_status") != "SUCCESS"
            or diagnosis.get("terminal_structured_object_admitted") is not False
            or diagnosis.get("final_agent_response") != '{"answer": "unavailable"}'
            or diagnosis.get("final_agent_response_payload_sha256") != PLAN_MODE_RESPONSE_SHA256
            or diagnosis.get("observed_denied_tool_names")
            != ["read_url_content", "search_web", "view_file"]
            or diagnosis.get("command_write_subagent_coverage") != "NOT_EXERCISED"
            or diagnosis.get("denial_message") != DENIAL_PROTOCOL_MESSAGE
            or diagnosis.get("all_attempted_tools_confirmed_pre_denied_with_empty_error_completion")
            is not True
            or diagnosis.get("settings_hooks_plugins_restored") is not True
            or diagnosis.get("causality")
            != "plan mode readonly behavior is documented; cause of missing structured object is not independently established"
        ):
            raise BudgetError("PLAN_MODE_REPAIR_DIAGNOSIS_NOT_ELIGIBLE")
        source, snapshot, snapshot_sha = (
            diagnosis.get(key)
            for key in ("source_database", "source_snapshot_path", "source_snapshot_sha256")
        )
        if (
            not isinstance(source, str)
            or not Path(source).is_absolute()
            or Path(source).name != PLAN_MODE_REPAIR_CONVERSATION + ".db"
            or not isinstance(snapshot, str)
            or not Path(snapshot).is_absolute()
            or Path(snapshot).name != "owned-plan-mode-snapshot.sqlite"
            or Path(snapshot).parent != Path(approval["diagnosis_path"]).parent
            or not isinstance(snapshot_sha, str)
            or re.fullmatch(r"[0-9a-f]{64}", snapshot_sha) is None
        ):
            raise BudgetError("PLAN_MODE_REPAIR_SOURCE_FINGERPRINT_INVALID")
        snapshot_path = Path(snapshot)
        if (
            any(node.is_symlink() for node in (snapshot_path, *snapshot_path.parents))
            or not snapshot_path.is_file()
        ):
            raise BudgetError("PLAN_MODE_REPAIR_SOURCE_FINGERPRINT_INVALID")
        with snapshot_path.open("rb") as source_stream:
            if hashlib.file_digest(source_stream, "sha256").hexdigest() != snapshot_sha:
                raise BudgetError("PLAN_MODE_REPAIR_SOURCE_FINGERPRINT_CHANGED")
        return approval

    def _plan_mode_repair(
        self, rows: list[dict], records: list[dict], denial_protocol_repair: dict | None
    ) -> dict | None:
        self._owned()
        pin = self._read("head.json").get("plan_mode_repair_sha256")
        path = self._path(PLAN_MODE_REPAIR_FILE)
        if pin is None and not path.exists():
            return None
        if (
            not isinstance(pin, str)
            or re.fullmatch(r"[0-9a-f]{64}", pin) is None
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != pin
        ):
            raise BudgetError("PLAN_MODE_REPAIR_JOURNAL_UNVERIFIED")
        amendment = self._read(PLAN_MODE_REPAIR_FILE)
        if (
            set(amendment) != {"version", "approval", "approval_sha256", "caps", "created_at"}
            or amendment.get("version") != PLAN_MODE_REPAIR_AMENDMENT_VERSION
            or amendment.get("caps") != self.caps
            or amendment.get("approval_sha256") != _sha(amendment.get("approval"))
        ):
            raise BudgetError("PLAN_MODE_REPAIR_JOURNAL_UNVERIFIED")
        self._validate_plan_mode_repair_approval(
            amendment["approval"], rows, records, denial_protocol_repair
        )
        return amendment

    def approve_plan_mode_repair(self, approval: dict) -> dict:
        """Append only the fifth synthetic configuration repair; never admit its raw JSON."""
        rows, records = self._state()
        recovery = self._recovery(rows, records)
        startup_repair = self._startup_repair(rows, records, recovery)
        plugin_startup_repair = self._plugin_startup_repair(rows, records, recovery, startup_repair)
        denial_protocol_repair = self._denial_protocol_repair(rows, records, plugin_startup_repair)
        existing = self._plan_mode_repair(rows, records, denial_protocol_repair)
        self._validate_plan_mode_repair_approval(approval, rows, records, denial_protocol_repair)
        if existing is not None:
            if existing["approval"] != approval:
                raise BudgetError("PLAN_MODE_REPAIR_APPROVAL_CHANGED")
            return existing
        if len(rows) != 5:
            raise BudgetError("PLAN_MODE_REPAIR_MUST_PRECEDE_NEW_ATTEMPTS")
        amendment = {
            "version": PLAN_MODE_REPAIR_AMENDMENT_VERSION,
            "approval": approval,
            "approval_sha256": _sha(approval),
            "caps": dict(self.caps),
            "created_at": datetime.now(UTC).isoformat(),
        }
        raw = self._exclusive(PLAN_MODE_REPAIR_FILE, amendment)
        self._head(rows, plan_mode_repair_sha256=hashlib.sha256(raw).hexdigest())
        return amendment

    def reserve(self, phase: str, metadata: dict | None = None) -> str:
        if phase not in self.caps:
            raise BudgetError("INVALID_BUDGET_PHASE")
        rows, records = self._state()
        recovery = self._recovery(rows, records)
        startup_repair = self._startup_repair(rows, records, recovery)
        plugin_startup_repair = self._plugin_startup_repair(rows, records, recovery, startup_repair)
        denial_protocol_repair = self._denial_protocol_repair(rows, records, plugin_startup_repair)
        plan_mode_repair = self._plan_mode_repair(rows, records, denial_protocol_repair)
        active_policy = (
            plan_mode_repair["approval"]["policy_hash"]
            if plan_mode_repair is not None
            else denial_protocol_repair["approval"]["policy_hash"]
            if denial_protocol_repair is not None
            else plugin_startup_repair["approval"]["policy_hash"]
            if plugin_startup_repair is not None
            else startup_repair["approval"]["policy_hash"]
            if startup_repair is not None
            else (recovery["approval"]["policy_hash"] if recovery is not None else None)
        )
        if active_policy is not None and (
            not isinstance(metadata, dict) or metadata.get("policy_hash") != active_policy
        ):
            raise BudgetError("RECOVERY_POLICY_MISMATCH")
        for row in rows:
            outcome = self._path(row["attempt_id"] + ".result.json")
            if not outcome.exists():
                raise BudgetError("UNFINISHED_ATTEMPT_REQUIRES_RECONCILIATION")
            result = self._read(outcome.name)
            recovered = (
                (recovery is not None and row["attempt_id"] == RECOVERABLE_ATTEMPT)
                or (startup_repair is not None and row["attempt_id"] == STARTUP_REPAIR_ATTEMPT)
                or (
                    plugin_startup_repair is not None
                    and row["attempt_id"] == PLUGIN_STARTUP_REPAIR_ATTEMPT
                )
                or (
                    denial_protocol_repair is not None
                    and row["attempt_id"] == DENIAL_PROTOCOL_REPAIR_ATTEMPT
                )
                or (plan_mode_repair is not None and row["attempt_id"] == PLAN_MODE_REPAIR_ATTEMPT)
            )
            if result.get("reservation_sha256") != row["sha256"] or (
                result.get("status") != "COMPLETED" and not recovered
            ):
                raise BudgetError("PRIOR_ATTEMPT_FAILED_OR_UNVERIFIED")
        if sum(record["phase"] == phase for record in records) >= self.caps[phase]:
            raise BudgetError("BUDGET_EXHAUSTED")
        index = len(rows) + 1
        attempt_id = f"attempt-{index:04d}"
        raw = self._exclusive(
            attempt_id + ".json",
            {
                "version": "StockOSAGYAttemptV1",
                "index": index,
                "phase": phase,
                "owner": self.owner,
                "status": "RESERVED",
                "metadata": metadata or {},
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        row = {"attempt_id": attempt_id, "phase": phase, "sha256": hashlib.sha256(raw).hexdigest()}
        self._head([*rows, row])
        return attempt_id

    def finish(self, attempt_id: str, status: str, details: dict | None = None) -> None:
        rows, records = self._state()
        recovery = self._recovery(rows, records)
        startup_repair = self._startup_repair(rows, records, recovery)
        plugin_startup_repair = self._plugin_startup_repair(rows, records, recovery, startup_repair)
        denial_protocol_repair = self._denial_protocol_repair(rows, records, plugin_startup_repair)
        self._plan_mode_repair(rows, records, denial_protocol_repair)
        if status not in {"COMPLETED", "FAILED", "ABORTED"}:
            raise BudgetError("INVALID_ATTEMPT_STATUS")
        matches = [
            (row, record)
            for row, record in zip(rows, records, strict=True)
            if row["attempt_id"] == attempt_id
        ]
        if len(matches) != 1 or matches[0][1].get("owner") != self.owner:
            raise BudgetError("ATTEMPT_OWNERSHIP_UNVERIFIED")
        row, _ = matches[0]
        self._exclusive(
            attempt_id + ".result.json",
            {
                "status": status,
                "reservation_sha256": row["sha256"],
                "details": details or {},
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )
