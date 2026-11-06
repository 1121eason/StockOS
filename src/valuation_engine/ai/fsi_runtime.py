"""Offline exclusion primitive; no provider launch, PID discovery or termination.

Observed process state is supplied data, not attested by this module. Unknown or
exceptional termination retains the lock for explicit investigation. This cannot
unlock live execution or substitute for native kernel/isolation receipts.
"""

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

PROVIDER_EXECUTABLES = {"codex", "claude", "gemini", "agy"}


def process_observation(raw, *, exit_code):
    """Conservative complete `ps pid,ppid,comm` parsing; no implicit allowlist.

    A desktop/parent process with a provider-like name is also unresolved. A
    future reviewed classification policy is required to exempt it. Missing,
    malformed and failed observations are never proof that a process ended.
    """
    if exit_code != 0 or not isinstance(raw, str) or not raw.strip():
        raise ValueError("Process observation failed or is empty")
    rows, seen, unresolved = [], set(), []
    for line in raw.splitlines():
        fields = line.split(None, 2)
        if len(fields) != 3:
            raise ValueError("Unparseable process observation")
        try:
            pid, parent = int(fields[0]), int(fields[1])
        except ValueError:
            raise ValueError("Invalid process identifier") from None
        if pid <= 0 or parent < 0 or pid in seen:
            raise ValueError("Invalid or duplicate process identity")
        seen.add(pid)
        name = Path(fields[2]).name.lower()
        if name in PROVIDER_EXECUTABLES:
            unresolved.append(pid)
        rows.append({"pid": pid, "ppid": parent, "executable": fields[2]})
    return {
        "processes": rows,
        "unresolved_provider_pids": unresolved,
        "raw_observation": raw,
        "observation_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "source_authenticity": "SUPPLIED_OBSERVATION_NOT_ATTESTED",
        "live_ready": False,
    }


def collect_process_observation():
    """Read-only native collector, never a model/probe launcher; not used by tests."""
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid=,comm="],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return process_observation(result.stdout, exit_code=result.returncode)


def shared_offline_lease(state_directory, observation):
    """One fixed lock within the shared state root, independent of quarter/run ID.

    Observations remain assertions. This is an offline contract only; callers
    cannot use it to bypass the existing unconditional live-mode rejection.
    """
    root = Path(state_directory).resolve(strict=True)
    if not root.is_dir() or observation.get("live_ready") is not False:
        raise ValueError("Invalid offline runtime observation")
    rebuilt = process_observation(observation.get("raw_observation"), exit_code=0)
    if json.dumps(rebuilt, sort_keys=True) != json.dumps(observation, sort_keys=True):
        raise ValueError("Process classification was altered")
    return OfflineLease(
        root / "global-active.lock", unresolved_processes=observation["unresolved_provider_pids"]
    )


class OfflineLease:
    def __init__(self, path, *, unresolved_processes):
        self.path = Path(path)
        if unresolved_processes != []:
            raise ValueError("Unresolved or unknown provider process state")
        self.identity = {"owner": uuid.uuid4().hex, "pid": os.getpid(), "mode": "OFFLINE_ONLY"}
        self.payload = json.dumps(self.identity, sort_keys=True).encode()
        self.fd: int | None = None
        self.inode: int | None = None

    def __enter__(self):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        self.fd = os.open(self.path, flags, 0o600)
        try:
            if os.write(self.fd, self.payload) != len(self.payload):
                raise OSError("Partial lease write; lock retained")
            os.fsync(self.fd)
            self.inode = os.fstat(self.fd).st_ino
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise
        return self

    def finish(self, *, residual_processes):
        if self.fd is None:
            raise ValueError("No active lease")
        if residual_processes != []:
            raise ValueError("Unknown or residual process state; lock retained")
        if (
            self.path.is_symlink()
            or self.path.stat().st_ino != self.inode
            or self.path.read_bytes() != self.payload
        ):
            raise ValueError("Lease owner changed; lock retained")
        self.path.unlink()

    def __exit__(self, exc_type, exc, traceback):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        # Only an explicit finish() removes a clean lease; exceptions never do.
