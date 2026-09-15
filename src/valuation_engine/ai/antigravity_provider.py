"""Official Antigravity CLI adapter; no API, keyring or credential-store access."""

import json

from valuation_engine.ai.cli_provider import (
    CapabilityCLIProvider,
    antigravity_agent_definition,
    classify_failure,
    execute,
)
from valuation_engine.ai.provider import ProviderUnavailable
from valuation_engine.db.store import digest


class AntigravityCLIProvider(CapabilityCLIProvider):
    cli_name = "agy"
    provider_name = "antigravity_cli"
    required_flags = (
        "--print",
        "--input-format",
        "--output-format",
        "--json-schema",
        "--model",
        "--effort",
        "--agent",
        "--disable-slash-commands",
        "--log-file",
    )

    def __init__(self, model=None, executable=None, timeout=240, effort="high"):
        super().__init__(model, executable, timeout)
        self.effort = effort
        self._ready = False
        self._pinned_version = None
        self.settings.update(
            activation="independent_reviewer_or_quota_fallback",
            reasoning_effort=effort,
            tools=[],
            agent_name="qve-pit-analyst",
            customizations="requested_disabled",
            agent_contract_hash=digest(antigravity_agent_definition()),
        )

    def check(self):
        result = super().check()
        result.update(
            headless_support=result["non_interactive"],
            json_schema_support=result["structured_output"],
            model_selection_support=result["non_interactive"],
            reasoning_effort_support=result["non_interactive"],
        )
        if not result["non_interactive"]:
            return result
        version = result["cli_version"]
        if version != "1.2.2" or (self._pinned_version and version != self._pinned_version):
            self._ready = False
            if self._pinned_version:
                self.settings["cli_version"] = self._pinned_version
            result.update(ready=False, reason="UNSUPPORTED_CLI_CONTRACT")
            return result
        self._pinned_version = version
        if self.effort not in {"low", "medium", "high"}:
            result.update(ready=False, reason="UNSUPPORTED_REASONING_EFFORT")
            return result
        result.update(
            ready=self._ready,
            authentication="usable" if self._ready else "not_checked",
            reason=None if self._ready else "LIVE_PROBE_REQUIRED",
        )
        return result

    def probe(self):
        status = self.check()
        if not status["non_interactive"] or status["reason"] not in {None, "LIVE_PROBE_REQUIRED"}:
            return status
        # The official model command is read-only and reports missing authentication.
        raw, meta = execute([self.executable, "models"], timeout=20)
        failure = meta.get("operational_failure") or classify_failure(raw)
        if meta["exit_code"] or failure:
            return {
                **status,
                "ready": False,
                "authentication": "unavailable",
                "reason": failure or "MODEL_DISCOVERY_FAILED",
                "discovery_metadata": meta,
            }
        if self.model_name == "unavailable":
            return {
                **status,
                "ready": False,
                "reason": "MODEL_SELECTION_REQUIRED",
                "available_models": raw.decode(errors="replace")[:12000],
            }
        result = self._request(
            "provider_check",
            {
                "system": 'Return only {"ok":true}; do not use any tools or external context.',
                "task": "Connection check",
                "untrusted_data": {},
                "response_schema": {
                    "type": "object",
                    "properties": {"ok": {"const": True}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
            },
        )
        self._ready = result["structured_output"] == {"ok": True}
        if result["response_model"] != "unavailable":
            self.settings.update(
                actual_model=result["response_model"],
                model_identity_confidence=result["execution_metadata"]["model_identity_confidence"],
            )
        return {
            **self.check(),
            "probe": result,
            "authentication": "usable"
            if result["raw_response"].get("result", {}).get("status") == "SUCCESS"
            else "unavailable",
            "reason": None if self._ready else result["execution_metadata"]["failure_kind"],
        }

    def request(self, stage, exact_prompt):
        if not self._ready or not self.check()["ready"]:
            raise ProviderUnavailable("Antigravity live structured/no-tools probe required")
        return self._request(stage, exact_prompt)

    def _request(self, stage, exact_prompt):
        content = json.dumps(
            {"task": exact_prompt["task"], "untrusted_data": exact_prompt["untrusted_data"]},
            sort_keys=True,
            default=str,
        )
        stdin = json.dumps({"event": "user", "message": {"content": content}}) + "\n"
        argv = [
            self.executable,
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--json-schema",
            json.dumps(exact_prompt["response_schema"]),
            "--model",
            self.model_name,
            "--effort",
            self.effort,
            "--agent",
            "qve-pit-analyst",
            "--disable-slash-commands",
            "--log-file",
            "{QVE_LOG}",
        ]
        stdout, meta = execute(
            argv, stdin=stdin, timeout=self.timeout, antigravity_system=exact_prompt["system"]
        )
        events = []
        malformed = False
        try:
            events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            if not all(isinstance(e, dict) for e in events):
                raise ValueError("Expected NDJSON objects")
        except ValueError:
            events, malformed = [], True
        inits = [e for e in events if e.get("event") == "init"]
        results = [e.get("result") for e in events if e.get("event") == "result"]
        envelope = results[0] if len(results) == 1 and isinstance(results[0], dict) else {}
        initialization = inits[0] if len(inits) == 1 else {}
        init = initialization.get("init", initialization)
        init = init if isinstance(init, dict) else {}
        tools = init.get("tools")
        tool_events = [
            e
            for e in events
            if e.get("event") == "step_update"
            and e.get("step_update", {}).get("step_type") == "tool"
        ]
        # finish is the CLI's terminal structured-answer emitter, not external access.
        external_tool_events = [
            e for e in tool_events if e.get("step_update", {}).get("tool_name") != "finish"
        ]
        isolation_verified = (
            isinstance(tools, list)
            and all(isinstance(t, str) for t in tools)
            and set(tools) <= {"finish"}
            and init.get("agent") == "qve-pit-analyst"
            and not external_tool_events
        )
        actual = init.get("model")
        actual = actual if isinstance(actual, str) else "unavailable"
        failure = classify_failure(envelope.get("error", "")) or meta.get("operational_failure")
        if meta["timed_out"]:
            failure = "timeout"
        elif malformed and not meta["exit_code"]:
            failure = "schema_failure"
        elif meta["exit_code"] or envelope.get("status") != "SUCCESS":
            failure = failure or "provider_failure"
        elif malformed or not isinstance(envelope.get("structured_output"), dict):
            failure = "schema_failure"
        elif not isolation_verified:
            failure = "ANTIGRAVITY_CLI_PIT_ISOLATION_UNSUPPORTED"
        meta.update(
            self.settings,
            executable_path=self.executable,
            prompt_hash=digest([stage, exact_prompt]),
            actual_model=actual,
            model_identity_confidence="exposed" if actual != "unavailable" else "requested_only",
            failure_kind=failure,
            provider_execution_status=failure or "completed",
            tool_isolation_verified=isolation_verified,
            agent_name="qve-pit-analyst",
            actual_agent=init.get("agent"),
            agent_definition_hash=digest(antigravity_agent_definition(exact_prompt["system"])),
            advertised_tools=tools,
            forbidden_tool_count=sum(t != "finish" for t in tools)
            if isinstance(tools, list)
            else None,
            permission_mode="CLI_default_no_permission_bypass",
            sandbox_enabled=False,
            source_hashes=[digest(exact_prompt["untrusted_data"])],
            source_hash_scope="exact supplied untrusted_data envelope",
        )
        return {
            "structured_output": envelope.get("structured_output") if not failure else None,
            "response_model": actual,
            "raw_response": {
                "initialization": {k: init[k] for k in ("model", "agent", "tools") if k in init},
                "result": {
                    k: envelope[k]
                    for k in (
                        "status",
                        "structured_output",
                        "usage",
                        "duration_seconds",
                        "num_turns",
                    )
                    if k in envelope
                },
                "tool_event_count": len(tool_events),
                "external_tool_event_count": len(external_tool_events),
                "observed_tool_names": sorted(
                    {e.get("step_update", {}).get("tool_name", "unavailable") for e in tool_events}
                ),
            },
            "execution_metadata": meta,
        }
