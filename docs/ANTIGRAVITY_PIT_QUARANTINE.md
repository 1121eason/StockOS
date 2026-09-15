# Antigravity PIT quarantine

The tools: [] custom agent was loaded but did not remove the advertised catalog. V1 evidence is retained. V2 distinguishes advertised names from execution and combines temporary explicit denies, --sandbox, an empty cwd, stdin-only input and incremental stream monitoring. Prompt restrictions remain additional protection; frozen research policies are unchanged.

Implementation: src/valuation_engine/ai/antigravity_quarantine.py. Experimental entry point: scripts/run_agy_quarantine.py. It refuses a duplicate live cohort once experiment.json exists. The standard provider is not switched to V2. See M4_1_AGY_PIT_QUARANTINE_REPORT.md for all six real cases and Q1-Q10.

Any nested step_type=tool triggers immediate process-group termination and PIT_TOOL_ATTEMPT. Even finish is rejected. The monitor discards buffered partial analytical results. ACTIVE without a denial/result is UNKNOWN, not a successful-access count of zero. A synthetic no-evidence response that claims outside content is rejected even without a tool event. The original six-case receipt is immutable; the separate assessment documents the E/F review timing.

Temporary policy: read_file(*), write_file(*), read_url(*), execute_url(*), command(*), unsandboxed(*), mcp(*) in deny; allow/ask empty; toolPermission=strict; non-workspace access false; terminal sandbox true. The installed CLI recognizes those namespace names; no additional namespace was verified. Seven deny rules loaded, but pre-action enforcement was not proven. No permission bypass flag is used.

Only settings.json is backed up, never auth stores. Backup and replacement are atomic, mode 0600; original bytes/mode/existence are restored in finally. SIGTERM/SIGINT unwind cleanup; a journal handles hard crashes. A process lock prevents concurrent QVE experiments. If a crash leaves the temporary policy, run from the repository:

```sh
PYTHONPATH=src .venv/bin/python scripts/run_agy_quarantine.py --recover-settings
```

Recovery refuses a live owner. The journal lives next to the official settings file and is removed after restoration. On this machine the original settings file was absent and that state was restored. Settings with credential-like keys are refused before backup. Normal CLI auth remains entirely managed by the official CLI.

Known limitation: terminal sandbox is not full-provider network isolation, stream events are not proven to precede execution, and terminating the local process cannot certify remote cancellation. Six synthetic cases did not prove quarantine. No NVIDIA pilot or cohort was authorized by these failed gates; no 26-quarter expansion or M5.
