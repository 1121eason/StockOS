"""Bounded candidate-only CLI transport. Separate from the frozen V1 provider.

The V2 contract requires an explicit scope decision before use. It serializes
StockOS-controlled requests; it does not assert that the host has no other AI
applications. Raw requests and streams stay in a private execution directory.
"""

import copy
import json
import os
import selectors
import signal
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from valuation_engine.ai.cli_provider import subscription_environment
from valuation_engine.ai.codex_pit import CONFIG, MODEL, SAFETY
from valuation_engine.ai.native_preflight import PACKAGE_HASH, PROTOCOL_HASH, canonical, sha
from valuation_engine.ai.provider import strict_schema

CLI_VERSION = "codex-cli 0.163.0-alpha.10.2"
CLI_SHA = "1afb28c01d7d49e892bd75f11076b10f1451e34e0ee308a95e5ab7f69f9c84fe"
CONFIG_V2 = copy.deepcopy(CONFIG)
LEGACY_CONTRACT_HASH = "dcc0d45a1a9b49141fd916bf94371a11fa1e0e60c9541a69fb89abab0ff9ffb9"
RECOVERY_LEDGER_SHA = "5afcc118fc3dc0111a067921a793f5fc02e90affe43967e5cd374183ee1302ed"
CONTRACT = {
    "version": "NVDASingleQuarterExecutionV2.1",
    "quarter": "FY2023-Q2",
    "protocol_hash": PROTOCOL_HASH,
    "package_hash": PACKAGE_HASH,
    "model": MODEL,
    "cli_version": CLI_VERSION,
    "cli_sha256": CLI_SHA,
    "configuration": CONFIG_V2,
    "exclusion_scope": "ONE_STOCKOS_CONTROLLED_PROVIDER_REQUEST_ACROSS_SHARED_STATE_ROOT",
    "host_baseline": "RECORDED_WITHOUT_TERMINATING_OR_CERTIFYING_UNRELATED_PROCESSES",
    "model_identity": "REQUESTED_AND_CLI_REPORTED_ONLY_UNLESS_BACKEND_EXPOSES_IDENTITY",
    "diagnostic_attempt_cap": 8,
    "research_attempt_cap": 44,
    "attempts_per_method": 22,
    "total_attempt_cap": 52,
    "recovery": {
        "prior_contract_hash": LEGACY_CONTRACT_HASH,
        "retained_failed_attempt_sha256": RECOVERY_LEDGER_SHA,
        "additional_attempts": 1,
        "requires_separate_bound_user_approval": True,
        "startup_notice_policy": "EXACT_PINNED_PRE_TURN_NOTICES_ONLY",
    },
    "outer_retries": 0,
    "attempt_accounting": "CLI_INVOCATIONS_NOT_INDEPENDENT_HTTP_REQUEST_COUNTS",
    "provider_internal_retries": "NOT_INDEPENDENTLY_MEASURED_BUILTIN_OPENAI_PROVIDER",
    "comparison_status": "UNVERIFIED_MODEL_SNAPSHOT_IDENTITY",
    "promotion_ready": False,
    "formal_db_writes": False,
}
CONTRACT_HASH = sha(canonical(CONTRACT).encode())

# This pinned CLI emits nonfatal startup notices as item.type=error. Only these
# exact pre-turn notices are admissible; tools, errors after turn.start and all
# unknown messages retain the original fail-closed behavior.
STARTUP_NOTICES = frozenset(
    {
        "Under-development features enabled: skip_host_skill_discovery. Under-development features are incomplete and may behave unpredictably. To suppress this warning, set `suppress_unstable_features_warning = true` in "
        + str(Path.home() / ".codex/config.toml")
        + ".",
        "Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.",
    }
)


def now():
    return datetime.now(UTC).isoformat()


def descendant_ids(rows, root, known=()):
    owned = {root, *known}
    changed = True
    while changed:
        changed = False
        for pid, parent in rows:
            if parent in owned and pid not in owned:
                owned.add(pid)
                changed = True
    return owned - {root}


def native_process_rows(directory, name):
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,comm="], capture_output=True, text=True, timeout=5
    )
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("Native process census unavailable")
    rows = []
    seen = set()
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) != 3:
            raise ValueError("Malformed native process census")
        pid, parent = int(fields[0]), int(fields[1])
        if pid <= 0 or parent < 0 or pid in seen:
            raise ValueError("Invalid native process census")
        seen.add(pid)
        rows.append((pid, parent))
    (directory / name).write_text(result.stdout)
    return rows


def write_json(path: Path, value, *, exclusive=False):
    payload = (canonical(value) + "\n").encode()
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        raise


def approved_failure(state_root: Path, approval: dict) -> Path | None:
    """Admit only the one retained startup failure explicitly approved by the user.

    This is not a retry policy. All bytes stay bound to the original journal,
    response and raw streams; any subsequent failure still stops the run.
    """
    recovery = approval.get("recovery")
    if recovery is None:
        return None
    path = state_root / "attempt-0001.json"
    if (
        approval.get("contract_hash") != CONTRACT_HASH
        or approval.get("decision") != "APPROVED_BY_USER"
        or approval.get("shared_state_root") != str(state_root.resolve())
        or not recovery.get("user_instruction")
        or recovery.get("additional_diagnostic_attempts") != 1
        or recovery.get("ledger_sha256") != RECOVERY_LEDGER_SHA
        or path.is_symlink()
        or sha(path.read_bytes()) != RECOVERY_LEDGER_SHA
    ):
        raise ValueError("Recovery approval or retained failed journal changed")
    record = json.loads(path.read_bytes())
    if any(
        record.get(k) != v
        for k, v in {
            "contract_hash": LEGACY_CONTRACT_HASH,
            "index": 1,
            "phase": "diagnostic",
            "stage": "isolation_1",
            "method": None,
            "status": "FAILED",
            "cleanup": "CLEAN",
        }.items()
    ):
        raise ValueError("Only the original clean startup failure is recoverable")
    result_path = Path(recovery["result_path"])
    if result_path.is_symlink() or result_path.parent.is_symlink():
        raise ValueError("Symlink recovery evidence refused")
    result = json.loads(result_path.read_bytes())
    if (
        sha(canonical(result).encode()) != record.get("result_sha256")
        or result.get("failure") != "ValueError"
        or result.get("group_absent") is not True
        or result.get("remaining_observed_descendants") != []
        or result.get("structured_output") is not None
        or result.get("turn_completed") is not False
    ):
        raise ValueError("Original failure result binding changed")
    for name in ("stdout.jsonl", "stderr.txt"):
        stream = result_path.parent / name
        if stream.is_symlink() or sha(stream.read_bytes()) != result.get(name + "_sha256"):
            raise ValueError("Original failure raw stream changed")
    return path


class Execution:
    """One explicit approval, one fixed shared lock, non-resetting call journal."""

    def __init__(self, state_root: Path, output: Path, approval: dict, executable: Path):
        if (
            approval.get("contract_hash") != CONTRACT_HASH
            or approval.get("decision") != "APPROVED_BY_USER"
            or not approval.get("user_instruction")
            or approval.get("shared_state_root") != str(state_root.resolve())
        ):
            raise ValueError("V2 scope and diagnostic budget require a bound user decision")
        self.root, self.output, self.exe = state_root, output, executable
        self.approval = copy.deepcopy(approval)
        self.owner = uuid.uuid4().hex
        self.lock = state_root / "global-active.lock"
        self.fd: int | None = None
        self.pending = False
        self.halted = False
        self.research_authorized = False

    def __enter__(self):
        if self.root.is_symlink() or self.output.is_symlink():
            raise ValueError("Symlink execution roots refused")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fd = os.open(self.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self.identity = {
            "owner": self.owner,
            "pid": os.getpid(),
            "contract_hash": CONTRACT_HASH,
            "created_at": now(),
        }
        payload = canonical(self.identity).encode()
        if os.write(self.fd, payload) != len(payload):
            raise OSError("Partial lock write; retained")
        os.fsync(self.fd)
        self.inode = os.fstat(self.fd).st_ino
        # An execution root is never reused, including after a clean failure.
        try:
            self.output.mkdir(parents=True, exist_ok=False, mode=0o700)
            self.calls = []
            write_json(
                self.output / "contract.json",
                {**CONTRACT, "contract_hash": CONTRACT_HASH},
                exclusive=True,
            )
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise
        return self

    @property
    def active(self):
        if self.fd is None:
            return False
        try:
            return (
                os.fstat(self.fd).st_ino == self.inode
                and not self.lock.is_symlink()
                and self.lock.stat().st_ino == self.inode
                and json.loads(self.lock.read_text()) == self.identity
            )
        except (OSError, ValueError):
            return False

    def __exit__(self, kind, value, trace):
        try:
            if not self.pending and self.fd is not None:
                if self.lock.is_symlink() or self.lock.stat().st_ino != self.inode:
                    raise RuntimeError("Lock identity changed; retained")
                if json.loads(self.lock.read_text()) != self.identity:
                    raise RuntimeError("Lock owner changed; retained")
                self.lock.unlink()
        finally:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None

    def reserve(self, phase: str, stage: str, exact: dict, method: str | None):
        if not self.active:
            raise ValueError("Active owner-bound lease required")
        if self.pending or self.halted:
            raise ValueError("Pending or failed attempt; retry refused")
        if phase not in {"diagnostic", "research"}:
            raise ValueError("Unknown execution phase")
        if phase == "research" and not self.research_authorized:
            raise ValueError("Completed isolation and source gates required")
        records = sorted(self.root.glob("attempt-*.json"))
        recovered = approved_failure(self.root, self.approval)
        history = [json.loads(p.read_text()) for p in records]
        if any(
            p != recovered
            and (
                h.get("contract_hash") != CONTRACT_HASH
                or h.get("status") != "COMPLETED"
                or h.get("cleanup") != "CLEAN"
            )
            for p, h in zip(records, history, strict=True)
        ):
            raise ValueError("Existing ledger is incompatible, pending or failed")
        selected = [h for h in history if h["phase"] == phase]
        extra = int(recovered is not None)
        cap = 7 + extra if phase == "diagnostic" else 44
        if len(history) >= 51 + extra or len(selected) >= cap:
            raise ValueError("Shared attempt cap reached")
        if phase == "research" and (
            method not in {"B", "C"} or sum(h.get("method") == method for h in selected) >= 22
        ):
            raise ValueError("Method identity or attempt cap violation")
        index = len(records) + 1
        self.record = {
            "contract_hash": CONTRACT_HASH,
            "index": index,
            "phase": phase,
            "stage": stage,
            "method": method,
            "request_hash": sha(canonical(exact).encode()),
            "status": "PENDING",
            "owner": self.owner,
            "created_at": now(),
        }
        self.record_path = self.root / f"attempt-{index:04d}.json"
        write_json(self.record_path, self.record, exclusive=True)
        directory = self.output / f"call-{index:04d}"
        directory.mkdir(mode=0o700)
        write_json(directory / "request.json", exact, exclusive=True)
        self.pending = True
        return directory

    def request(self, phase: str, stage: str, exact: dict, *, method=None, timeout=None):
        maximum = 120 if phase == "diagnostic" else 180 if stage == "extract" else 600
        if timeout is None:
            timeout = maximum
        if timeout <= 0 or timeout > maximum:
            raise ValueError("Stage timeout outside the fixed bound")
        if sha(self.exe.read_bytes()) != CLI_SHA:
            raise ValueError("CLI binary changed")
        directory = self.reserve(phase, stage, exact, method)
        cwd = directory / "workspace"
        cwd.mkdir(mode=0o700)
        (cwd / "system.md").write_text(SAFETY + exact["system"])
        write_json(cwd / "schema.json", strict_schema(exact["response_schema"]), exclusive=True)
        argv = [
            str(self.exe),
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
            "--output-schema",
            str((cwd / "schema.json").resolve()),
            "-m",
            MODEL,
        ]
        for key, value in CONFIG_V2.items():
            argv.extend(["-c", f"{key}={value}"])
        argv.extend(
            ["-c", "model_instructions_file=" + json.dumps(str((cwd / "system.md").resolve())), "-"]
        )
        audit = {
            "started_at": now(),
            "failure": None,
            "structured_output": None,
            "turn_completed": False,
            "runner_signals": [],
            "group_absent": False,
            "actual_model": None,
            "requested_model": MODEL,
            "observed_descendants": [],
        }
        process = None
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=subscription_environment(),
                start_new_session=True,
            )
            audit["pid"], audit["pgid"] = process.pid, process.pid
            write_json(directory / "process.json", audit, exclusive=True)
            self._stream(process, exact, directory, audit, timeout)
        except BaseException as error:
            audit["failure"] = audit["failure"] or type(error).__name__
            if not isinstance(error, Exception):
                raise
        finally:
            if process is not None:
                try:
                    if not audit["failure"]:
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            audit["failure"] = "EXIT_NOT_COMPLETED_AFTER_OUTPUT"
                    if process.poll() is None:
                        audit["runner_signals"].append(
                            {"at": now(), "signal": "SIGKILL", "owned_pgid": process.pid}
                        )
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                    audit["exit_code"] = process.returncode
                    rows = native_process_rows(directory, "after-processes.txt")
                    tracked = descendant_ids(rows, process.pid, audit["observed_descendants"])
                    audit["remaining_observed_descendants"] = sorted(
                        tracked & {pid for pid, _ in rows}
                    )
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        audit["group_absent"] = True
                    if audit["remaining_observed_descendants"]:
                        audit["group_absent"] = False
                except BaseException as error:
                    audit["failure"] = "UNKNOWN_CLEANUP_" + type(error).__name__
                finally:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None and not stream.closed:
                            stream.close()
            else:
                audit["group_absent"] = True  # Popen failed before a child was returned.
            if audit["group_absent"] is not True:
                audit["failure"] = audit["failure"] or "UNKNOWN_RESIDUAL_PROCESS_GROUP"
            if (
                audit.get("exit_code") != 0
                or not audit["turn_completed"]
                or not isinstance(audit["structured_output"], dict)
            ):
                audit["failure"] = audit["failure"] or "INCOMPLETE_PROVIDER_RESPONSE"
            audit["completed_at"] = now()
            audit["workspace_files_after"] = sorted(p.name for p in cwd.iterdir())
            if audit["workspace_files_after"] != ["schema.json", "system.md"]:
                audit["failure"] = audit["failure"] or "CURATED_WORKSPACE_CHANGED"
            for name in ("stdout.jsonl", "stderr.txt"):
                if (directory / name).exists():
                    audit[name + "_sha256"] = sha((directory / name).read_bytes())
            write_json(directory / "result.json", audit, exclusive=True)
            self.record.update(
                status="COMPLETED" if not audit["failure"] else "FAILED",
                cleanup="CLEAN" if audit["group_absent"] else "UNKNOWN",
                result_sha256=sha(canonical(audit).encode()),
            )
            write_json(self.record_path, self.record)
            self.pending = not audit["group_absent"]
            self.halted = bool(audit["failure"])
            self.calls.append(copy.deepcopy(audit))
        if audit["failure"]:
            raise RuntimeError("Provider stopped; inspect the retained private result receipt")
        return {
            "structured_output": audit["structured_output"],
            "response_model": None,
            "raw_response": audit,
            "execution_metadata": {
                "provider_execution_status": "completed",
                "model_identity_status": "REQUESTED_ONLY",
                "requested_model": MODEL,
                "cli_version": CLI_VERSION,
                "execution_contract_hash": CONTRACT_HASH,
            },
        }

    def reject_semantic_result(self, reason):
        self.halted = True
        self.record.update(status="FAILED", semantic_failure=reason)
        write_json(self.record_path, self.record)

    @staticmethod
    def _stream(process, exact, directory, audit, timeout):
        start, size, buffer = time.monotonic(), 0, b""
        last_census, census_index = 0.0, 0
        pending = memoryview(
            canonical({"task": exact["task"], "untrusted_data": exact["untrusted_data"]}).encode()
        )
        with (
            (directory / "stdout.jsonl").open("xb") as stdout,
            (directory / "stderr.txt").open("xb") as stderr,
            selectors.DefaultSelector() as selector,
        ):
            for stream, name, events in [
                (process.stdin, "stdin", selectors.EVENT_WRITE),
                (process.stdout, "stdout", selectors.EVENT_READ),
                (process.stderr, "stderr", selectors.EVENT_READ),
            ]:
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, events, name)
            while selector.get_map():
                if time.monotonic() - last_census >= 1:
                    census_index += 1
                    rows = native_process_rows(directory, f"processes-{census_index:03d}.txt")
                    audit["observed_descendants"] = sorted(
                        descendant_ids(rows, process.pid, audit["observed_descendants"])
                    )
                    last_census = time.monotonic()
                if time.monotonic() - start > timeout:
                    raise TimeoutError("Bounded provider stage timed out")
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
                    data = os.read(key.fd, 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    destination = stdout if key.data == "stdout" else stderr
                    destination.write(data)
                    destination.flush()
                    size += len(data)
                    if size > 12_000_000:
                        raise ValueError("Provider stream limit")
                    if key.data != "stdout":
                        continue
                    buffer += data
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line.strip():
                            continue
                        event = json.loads(line)
                        kind = event.get("item", {}).get("type")
                        typ = event.get("type")
                        if (
                            typ == "item.completed"
                            and kind == "error"
                            and not audit.get("provider_turn_started")
                            and event["item"].get("message") in STARTUP_NOTICES
                        ):
                            audit.setdefault("startup_notices", []).append(event["item"]["message"])
                            continue
                        if typ == "turn.started":
                            audit["provider_turn_started"] = True
                        if typ not in {
                            "thread.started",
                            "turn.started",
                            "item.started",
                            "item.updated",
                            "item.completed",
                            "turn.completed",
                            "turn.failed",
                            "error",
                        } or kind not in {None, "agent_message", "reasoning"}:
                            raise ValueError("Tool, permission or unknown event attempted")
                        if typ == "item.completed" and kind == "agent_message":
                            audit["structured_output"] = json.loads(event["item"]["text"])
                        if typ == "turn.completed":
                            audit["turn_completed"] = True
                            audit["usage"] = event.get("usage")
                        if typ in {"turn.failed", "error"}:
                            raise RuntimeError("Provider failure event")
            if buffer.strip():
                raise ValueError("Incomplete JSONL record")
