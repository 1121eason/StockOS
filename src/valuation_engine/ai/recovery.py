"""Resume failed analyses using exact, schema-valid recorded extraction calls only.

This is a transport cache of real prior output, not a model substitute. Repeats must
use the original CLI provider directly. Sources and frozen prompts are not changed.
"""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from valuation_engine.ai.contracts import POLICY_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from valuation_engine.ai.provider import AIProvider
from valuation_engine.db.schema import AIAnalysisRun, AIAnalystSnapshot, AIProviderCall
from valuation_engine.db.store import digest


class RecoveryProvider(AIProvider):
    def __init__(self, delegate, calls):
        self.delegate = delegate
        self.provider_name = delegate.provider_name
        self.model_name = delegate.model_name
        self.model_version = delegate.model_version
        self.calls = calls
        self.settings = {
            **delegate.settings,
            "recovery_mode": "exact_failed_extraction",
            "recovery_source_call_ids": sorted(c["id"] for c in calls.values()),
        }

    def request(self, stage, exact_prompt):
        key = digest([stage, exact_prompt])
        cached = self.calls.get(key) if stage == "extract" else None
        if cached is None:
            return self.delegate.request(stage, exact_prompt)
        result = deepcopy(cached["raw"])
        result["execution_metadata"]["reused_from_call_id"] = cached["id"]
        result["execution_metadata"]["reused_at"] = datetime.now(UTC).isoformat()
        return result


def recovery_provider(db, delegate, prepared):
    """Only failed runs with identical PIT context, versions and requested model qualify."""
    records: dict[str, Any] = {}
    runs = db.scalars(
        select(AIAnalysisRun)
        .where(
            AIAnalysisRun.model_provider == delegate.provider_name,
            AIAnalysisRun.model_name == delegate.model_name,
            AIAnalysisRun.model_version == delegate.model_version,
            AIAnalysisRun.policy_version == POLICY_VERSION,
            AIAnalysisRun.prompt_version == PROMPT_VERSION,
            AIAnalysisRun.schema_version == SCHEMA_VERSION,
        )
        .order_by(AIAnalysisRun.id)
    )
    for run in runs:
        if run.settings_json.get("cli_version") != delegate.settings.get("cli_version"):
            continue
        if any(
            run.settings_json.get(k) != delegate.settings.get(k)
            for k in (
                "transport_version",
                "isolation_hash",
                "agent_contract_hash",
                "reasoning_effort",
            )
        ):
            continue
        if digest(run.context_json) != digest(prepared):
            continue
        if db.scalar(
            select(AIAnalystSnapshot.id).where(AIAnalystSnapshot.analysis_run_id == run.id)
        ):
            continue
        for call in db.scalars(
            select(AIProviderCall)
            .where(
                AIProviderCall.analysis_run_id == run.id,
                AIProviderCall.stage == "extract",
                AIProviderCall.status == "valid",
            )
            .order_by(AIProviderCall.id)
        ):
            if call.raw_output.get("execution_metadata", {}).get("reused_from_call_id"):
                continue
            if call.request_hash != digest([call.stage, call.exact_prompt]):
                raise ValueError("Recorded extraction prompt hash mismatch")
            if call.response_hash != digest(call.raw_output):
                raise ValueError("Recorded extraction response hash mismatch")
            records.setdefault(call.request_hash, {"id": call.id, "raw": call.raw_output})
    return RecoveryProvider(delegate, records) if records else delegate
