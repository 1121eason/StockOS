"""Append-only lifecycle receipts for bounded Codex PIT attempts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UNKNOWN_PROCESS_STATES = frozenset({"unknown", "termination_unconfirmed"})


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("short write while persisting Codex PIT receipt")
        remaining = remaining[written:]


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_immutable_json(path: str | Path, value: Any) -> None:
    """Publish a complete mode-0600 JSON file atomically without replacing a target."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True, default=str) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        # A hard link is an atomic no-replace publication on the same filesystem.
        os.link(temporary, target)
        _sync_directory(target.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def write_json_atomic(path: str | Path, value: Any) -> None:
    """Atomically replace a mutable progress file using a unique same-directory temp."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True, default=str) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, target)
        _sync_directory(target.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def workspace_fingerprint(root: str | Path) -> dict[str, Any]:
    """Capture changed-file hashes without reading local environment files."""
    root = Path(root)

    def git(*args: str) -> bytes:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, stdout=subprocess.PIPE
        ).stdout

    head = git("rev-parse", "HEAD").decode().strip()
    branch = git("branch", "--show-current").decode().strip()
    diff = git("diff", "HEAD", "--binary")
    tracked = git("diff", "HEAD", "--name-only", "-z").decode().split("\0")
    untracked = git("ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    changed = sorted(
        {
            path
            for path in tracked + untracked
            if path and not Path(path).name.startswith(".env")
        }
    )
    files = []
    for relative in changed:
        path = root / relative
        if path.is_symlink():
            content = os.readlink(path).encode()
        elif path.is_file():
            content = path.read_bytes()
        else:
            continue
        files.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        )
    status = git("status", "--porcelain=v1", "--untracked-files=all").decode().splitlines()
    return {
        "git_root": str(root.resolve()),
        "head": head,
        "branch": branch,
        "status_porcelain": status,
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "tracked_diff_bytes": len(diff),
        "changed_files": files,
    }


class AttemptInProgress(RuntimeError):
    """A prior attempt has no terminal receipt, so another must not start."""


class AttemptJournal:
    """Persist an immutable attempt directory and a fail-closed singleton lock."""

    def __init__(
        self,
        attempts_dir: str | Path,
        *,
        purpose: str,
        manifest: dict[str, Any] | None = None,
    ) -> None:
        self.attempts_dir = Path(attempts_dir)
        self.attempts_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.attempts_dir / "active.lock"
        self.attempt_id = (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12]
        )
        self.path = self.attempts_dir / self.attempt_id
        self.progress_path = self.path / "progress.jsonl"
        self._unknown_process_state = False
        self._closed = False
        self._lock_identity: tuple[int, int] | None = None

        lock_value = {
            "attempt_id": self.attempt_id,
            "created_at_utc": utc_now(),
            "launcher_pid": os.getpid(),
            "purpose": purpose,
            "state": "active_or_unknown",
        }
        try:
            descriptor = os.open(
                self.lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise AttemptInProgress(
                "A Codex PIT attempt lock exists; inspect its progress and confirm process state before retrying"
            ) from exc
        try:
            lock_stat = os.fstat(descriptor)
            self._lock_identity = (lock_stat.st_dev, lock_stat.st_ino)
            payload = (json.dumps(lock_value, sort_keys=True) + "\n").encode()
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

        try:
            self.path.mkdir()
            self.write_once(
                self.path / "manifest.json",
                {
                    "attempt_id": self.attempt_id,
                    "created_at_utc": lock_value["created_at_utc"],
                    "purpose": purpose,
                    "launcher_pid": os.getpid(),
                    **(manifest or {}),
                },
            )
            self.emit("attempt_created", status="started")
        except BaseException:
            # No provider process is launched by construction before this succeeds.
            if self._read_own_lock() is not None:
                self.lock_path.unlink(missing_ok=True)
            raise

    @property
    def process_state_unknown(self) -> bool:
        return self._unknown_process_state

    def mark_process_state_unknown(self) -> None:
        self._unknown_process_state = True

    @staticmethod
    def write_once(path: Path, value: Any) -> None:
        write_immutable_json(path, value)

    def emit(
        self,
        event: str,
        *,
        stage: str | None = None,
        status: str | None = None,
        failure_kind: str | None = None,
        **details: Any,
    ) -> None:
        if self._closed:
            raise RuntimeError("Attempt journal is already closed")
        record = {
            "attempt_id": self.attempt_id,
            "at_utc": utc_now(),
            "event": event,
        }
        if stage is not None:
            record["stage"] = stage
        if status is not None:
            record["status"] = status
        if failure_kind is not None:
            record["failure_kind"] = failure_kind
        record.update(details)
        if (
            failure_kind in UNKNOWN_PROCESS_STATES
            or status in UNKNOWN_PROCESS_STATES
            or details.get("process_state") in UNKNOWN_PROCESS_STATES
        ):
            self._unknown_process_state = True
        descriptor = os.open(
            self.progress_path,
            os.O_CREAT | os.O_APPEND | os.O_WRONLY,
            0o600,
        )
        try:
            payload = (json.dumps(record, sort_keys=True, default=str) + "\n").encode()
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _read_own_lock(self) -> dict[str, Any] | None:
        try:
            lock_stat = self.lock_path.stat()
            lock_value = json.loads(self.lock_path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(lock_value, dict):
            return None
        identity = (lock_stat.st_dev, lock_stat.st_ino)
        if identity != self._lock_identity or lock_value.get("attempt_id") != self.attempt_id:
            return None
        return lock_value

    def finish(
        self,
        *,
        status: str,
        failure_kind: str | None = None,
        error_type: str | None = None,
    ) -> None:
        if self._closed:
            return
        details: dict[str, Any] = {}
        if error_type is not None:
            details["error_type"] = error_type
        self.emit("finished", status=status, failure_kind=failure_kind, **details)
        if self._unknown_process_state:
            return
        if self._read_own_lock() is None:
            # A malformed, unreadable, or replaced lock is still a hard stop.
            return
        self.lock_path.unlink(missing_ok=True)
        self._closed = True
