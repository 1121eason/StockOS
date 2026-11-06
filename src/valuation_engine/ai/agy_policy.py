"""Reviewable temporary AGY settings transaction; no CLI or model invocation.

The fixed sibling lock coordinates StockOS policy writers. Other applications
need not honor it: observed inode/bytes/mode changes fail closed on restoration,
but ordinary filesystem APIs cannot atomically compare-and-rename against an
uncooperative concurrent writer. Pause other settings writers before live use.
"""

import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

POLICY_VERSION = "StockOSAGYProposedStrictPolicyV1"
HOOKS_POLICY_VERSION = "StockOSAGYTemporaryDisabledHooksV1"
PLUGINS_POLICY_VERSION = "StockOSAGYTemporaryDisabledPluginsV1"
DENIES = tuple(
    f"{name}(*)"
    for name in ("read_file", "write_file", "read_url", "execute_url", "command", "mcp")
)
OVERRIDES = {
    "toolPermission": "strict",
    "enableTerminalSandbox": True,
    "allowNonWorkspaceAccess": False,
    "useG1Credits": False,
}
MAX_SETTINGS_BYTES = 2_000_000


class PolicyError(RuntimeError):
    pass


class PolicyBusy(PolicyError):
    pass


class PolicyRestoreConflict(PolicyError):
    def __init__(self, reason: str, receipt: dict):
        super().__init__("RESTORE_CONFLICT: " + reason)
        self.receipt = receipt


@dataclass(frozen=True)
class FileState:
    exists: bool
    content: bytes = b""
    mode: int | None = None
    device: int | None = None
    inode: int | None = None

    def public(self) -> dict:
        return {
            "exists": self.exists,
            "sha256": hashlib.sha256(self.content).hexdigest(),
            "mode": self.mode,
            "device": self.device,
            "inode": self.inode,
            "size": len(self.content),
        }


def _safe_path(path: Path) -> Path:
    path = Path(path).absolute()
    if any(node.is_symlink() for node in (path, *path.parents)):
        raise PolicyError("SYMLINK_PATH_REFUSED")
    return path


def _snapshot(path: Path) -> FileState:
    _safe_path(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return FileState(False)
    except OSError as exc:
        raise PolicyError("SETTINGS_READ_UNVERIFIED") from exc
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_SETTINGS_BYTES:
            raise PolicyError("SETTINGS_NOT_BOUNDED_REGULAR_FILE")
        raw = stream.read(MAX_SETTINGS_BYTES + 1)
        after = os.fstat(stream.fileno())
    if (
        len(raw) > MAX_SETTINGS_BYTES
        or before.st_size != after.st_size
        or after.st_size != len(raw)
        or before.st_mtime_ns != after.st_mtime_ns
        or stat.S_IMODE(before.st_mode) != stat.S_IMODE(after.st_mode)
    ):
        raise PolicyError("CONCURRENT_SETTINGS_READ")
    try:
        current = path.lstat()
    except OSError as exc:
        raise PolicyError("CONCURRENT_SETTINGS_REPLACEMENT") from exc
    if (
        not stat.S_ISREG(current.st_mode)
        or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino)
        or stat.S_IMODE(current.st_mode) != stat.S_IMODE(after.st_mode)
    ):
        raise PolicyError("CONCURRENT_SETTINGS_REPLACEMENT")
    return FileState(True, raw, stat.S_IMODE(after.st_mode), after.st_dev, after.st_ino)


def _assert_state(path: Path, expected: FileState) -> None:
    if _snapshot(path) != expected:
        raise PolicyError("FILE_STATE_CHANGED")


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Non-JSON constant")


def _parse_document(original: FileState) -> dict:
    if not original.exists:
        return {}
    try:
        value = json.loads(
            original.content, object_pairs_hook=_json_pairs, parse_constant=_constant
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise PolicyError("INVALID_SETTINGS_JSON") from exc
    if not isinstance(value, dict):
        raise PolicyError("SETTINGS_OBJECT_REQUIRED")

    def inspect(node: Any):
        if isinstance(node, dict):
            for key, item in node.items():
                if re.search(
                    r"token|password|secret|api.?key|oauth|credential|authorization|bearer|private.?key|client.?secret",
                    key,
                    re.I,
                ):
                    raise PolicyError("CREDENTIAL_LIKE_SETTING_BACKUP_REFUSED")
                inspect(item)
        elif isinstance(node, list):
            for item in node:
                inspect(item)

    try:
        inspect(value)
    except RecursionError as exc:
        raise PolicyError("INVALID_SETTINGS_JSON") from exc
    return value


def proposed_settings(original: dict) -> dict:
    """Return the fixed proposal, preserving unrelated configuration values."""
    if "permissions" in original and not isinstance(original["permissions"], dict):
        raise PolicyError("PERMISSIONS_OBJECT_REQUIRED")
    return {
        **original,
        **OVERRIDES,
        "permissions": {
            **original.get("permissions", {}),
            "deny": list(DENIES),
            "allow": [],
            "ask": [],
        },
    }


def _json_bytes(value: dict) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def _exclusive(path: Path, raw: bytes, mode: int = 0o600) -> FileState:
    _safe_path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return _snapshot(path)


def _prepare(path: Path, raw: bytes, mode: int) -> tuple[Path, FileState]:
    _safe_path(path)
    fd, name = tempfile.mkstemp(prefix=".stockos-policy-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return temp, _snapshot(temp)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_journal(path: Path, value: dict) -> None:
    temp, _ = _prepare(path, _json_bytes(value), 0o600)
    try:
        os.replace(temp, path)
        _sync_directory(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _strict_transform(original: dict) -> tuple[dict, dict]:
    return proposed_settings(original), {
        **OVERRIDES,
        "permissions": {"deny": list(DENIES), "allow": [], "ask": []},
    }


def _disabled_hooks_transform(original: dict) -> tuple[dict, dict]:
    """Disable definitions without exposing their commands in audit metadata."""
    event_names = (
        "SessionStart",
        "PreToolUse",
        "PostToolUse",
        "PreInvocation",
        "PostInvocation",
        "Stop",
    )
    disabled = {}
    for name, definition in original.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(definition, dict):
            raise PolicyError("INVALID_HOOK_DEFINITION")
        if "enabled" in definition and type(definition["enabled"]) is not bool:
            raise PolicyError("INVALID_HOOK_DEFINITION")
        for event_name in event_names:
            if event_name in definition:
                handlers = definition[event_name]
                if not isinstance(handlers, list) or not all(
                    isinstance(handler, dict) for handler in handlers
                ):
                    raise PolicyError("INVALID_HOOK_DEFINITION")
        disabled[name] = {**definition, "enabled": False}
    return disabled, {"enabled": False, "disabled_hook_names": sorted(disabled)}


def _disabled_plugins_transform(original: dict) -> tuple[dict, dict]:
    """Preserve plugin metadata and user settings; override only enabled flags."""
    if "plugins" not in original:
        return dict(original), {"enabled": False, "disabled_plugin_names": []}
    plugins = original["plugins"]
    if not isinstance(plugins, dict):
        raise PolicyError("INVALID_PLUGINS_CONFIGURATION")
    disabled = {}
    for name, definition in plugins.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(definition, dict)
            or type(definition.get("enabled")) is not bool
        ):
            raise PolicyError("INVALID_PLUGIN_DEFINITION")
        disabled[name] = {**definition, "enabled": False}
    return {**original, "plugins": disabled}, {
        "enabled": False,
        "disabled_plugin_names": sorted(disabled),
    }


@contextmanager
def _temporary_document_policy(
    settings: Path,
    journal_dir: Path,
    *,
    policy_version: str,
    document_kind: str,
    transform: Callable[[dict], tuple[dict, dict]],
):
    """Apply only when explicitly called; restore exactly or retain recovery state.

    On conflict, the backup, recovery journal and owned lock remain for human
    reconciliation. There is no automatic recovery over an existing/foreign lock.
    """
    settings, journal_dir = _safe_path(settings), _safe_path(journal_dir)
    settings.parent.mkdir(parents=True, exist_ok=True)
    lock_path = settings.with_name(settings.name + ".stockos-strict-policy.lock")
    owner = uuid.uuid4().hex
    lock_raw = _json_bytes(
        {
            "version": policy_version,
            "owner": owner,
            "pid": os.getpid(),
            "settings": str(settings),
            "created_at": datetime.now(UTC).isoformat(),
        }
    )
    try:
        lock_state = _exclusive(lock_path, lock_raw)
    except FileExistsError as exc:
        raise PolicyBusy("EXISTING_POLICY_LOCK_REFUSED") from exc
    receipt: dict[str, Any] = {
        "version": policy_version,
        "owner": owner,
        document_kind: str(settings),
        "target": str(settings),
        "document_kind": document_kind,
        "owner_lock": str(lock_path),
        "status": "PREPARING",
        "applied": False,
        "restored": False,
        "backup_removed": False,
        "global_settings_modified": False,
        "global_hooks_modified": False,
        "global_plugins_modified": False,
        "global_configuration_modified": False,
        "provider_calls": 0,
    }
    original = None
    backup_state = None
    installed = None
    temp = None
    recovery = None
    backup = None
    conflict = False

    def mark_conflict(reason: str) -> NoReturn:
        nonlocal conflict
        conflict = True
        receipt.update(status="RESTORE_CONFLICT", restored=False, conflict_reason=reason)
        if recovery is not None:
            try:
                _write_journal(recovery, receipt)
            except (OSError, PolicyError):
                # Keep the prior durable recovery journal and original-byte backup.
                pass
        raise PolicyRestoreConflict(reason, receipt)

    try:
        original = _snapshot(settings)
        proposed, policy_metadata = transform(_parse_document(original))
        payload = _json_bytes(proposed)
        journal_dir.mkdir(parents=True, exist_ok=True)
        owner_dir = journal_dir / ("policy-" + owner)
        owner_dir.mkdir(mode=0o700)
        backup, recovery = owner_dir / "original.bin", owner_dir / "recovery.json"
        backup_state = _exclusive(backup, original.content, 0o600)
        receipt.update(
            original=original.public(),
            backup_path=str(backup),
            recovery_journal=str(recovery),
            proposed_sha256=hashlib.sha256(payload).hexdigest(),
            proposed_mode=0o600,
            policy_overrides=policy_metadata,
        )
        temp, installed = _prepare(settings, payload, 0o600)
        receipt.update(status="ABOUT_TO_APPLY", installed=installed.public())
        _write_journal(recovery, receipt)
        _assert_state(lock_path, lock_state)
        _assert_state(settings, original)
        os.replace(temp, settings)
        temp = None
        receipt.update(applied=True, global_configuration_modified=True)
        receipt[f"global_{document_kind}_modified"] = True
        _sync_directory(settings.parent)
        _assert_state(settings, installed)
        receipt["status"] = "APPLIED"
        _write_journal(recovery, receipt)
        yield receipt
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
        if installed is not None and original is not None:
            # Account for an interrupted rename: the prepared inode is known
            # before installation, so ambiguous partial application fails closed.
            try:
                current = _snapshot(settings)
                _assert_state(lock_path, lock_state)
                if receipt["applied"] or current == installed:
                    if current != installed:
                        mark_conflict("INSTALLED_SETTINGS_CHANGED")
                    if backup is None or backup_state is None:
                        mark_conflict("ORIGINAL_BACKUP_UNVERIFIED")
                    _assert_state(backup, backup_state)
                    if original.exists:
                        if original.mode is None:
                            mark_conflict("ORIGINAL_MODE_UNVERIFIED")
                        restored_temp, restored_state = _prepare(
                            settings, original.content, original.mode
                        )
                        try:
                            _assert_state(settings, installed)
                            _assert_state(lock_path, lock_state)
                            os.replace(restored_temp, settings)
                            _sync_directory(settings.parent)
                        finally:
                            restored_temp.unlink(missing_ok=True)
                        _assert_state(settings, restored_state)
                    else:
                        _assert_state(settings, installed)
                        _assert_state(lock_path, lock_state)
                        settings.unlink()
                        _sync_directory(settings.parent)
                        _assert_state(settings, FileState(False))
                    receipt.update(
                        status="RESTORED",
                        restored=True,
                        restored_sha256=hashlib.sha256(original.content).hexdigest(),
                    )
                elif current != original:
                    mark_conflict("AMBIGUOUS_PARTIAL_APPLICATION")
                else:
                    receipt["status"] = "NOT_APPLIED"
            except PolicyRestoreConflict:
                raise
            except (OSError, PolicyError, TypeError) as exc:
                mark_conflict(type(exc).__name__)
        if not conflict:
            try:
                _assert_state(lock_path, lock_state)
                if backup is not None and backup_state is not None:
                    _assert_state(backup, backup_state)
                    backup.unlink()
                    receipt["backup_removed"] = True
                if recovery is not None:
                    _write_journal(recovery, receipt)
                _assert_state(lock_path, lock_state)
                lock_path.unlink()
                _sync_directory(lock_path.parent)
            except (OSError, PolicyError) as exc:
                mark_conflict(type(exc).__name__)


@contextmanager
def proposed_strict_policy(settings: Path, journal_dir: Path):
    """Temporarily apply the fixed strict settings policy; preserve the public API."""
    with _temporary_document_policy(
        settings,
        journal_dir,
        policy_version=POLICY_VERSION,
        document_kind="settings",
        transform=_strict_transform,
    ) as receipt:
        yield receipt


@contextmanager
def temporary_disabled_hooks(hooks_path: Path, journal_dir: Path):
    """Temporarily disable global hook definitions, restoring exact bytes/mode.

    Hook commands remain only in the private original-byte backup and installed
    configuration. Receipts expose names and hashes, never command contents.
    No hook is executed by this context manager.
    """
    with _temporary_document_policy(
        hooks_path,
        journal_dir,
        policy_version=HOOKS_POLICY_VERSION,
        document_kind="hooks",
        transform=_disabled_hooks_transform,
    ) as receipt:
        yield receipt


@contextmanager
def temporary_disabled_plugins(config: Path, journal_dir: Path):
    """Temporarily disable configured plugins, restoring exact bytes and mode.

    Only each plugin's enabled flag changes. Other configuration, installedFrom
    metadata and userSettings remain intact; receipts expose names, not values.
    Credential-like settings are rejected before any private backup is created.
    """
    with _temporary_document_policy(
        config,
        journal_dir,
        policy_version=PLUGINS_POLICY_VERSION,
        document_kind="plugins",
        transform=_disabled_plugins_transform,
    ) as receipt:
        yield receipt
