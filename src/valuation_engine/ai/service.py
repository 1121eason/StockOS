"""Append-only orchestration. Providers receive plain data and have no DB/session capability."""

from datetime import UTC, datetime
from typing import get_args

from sqlalchemy import select

from valuation_engine.ai.contracts import (
    POLICY_VERSION,
    PROMPT_VERSION,
    SCHEMA_VERSION,
    Challenges,
    Extraction,
    FeatureName,
    Synthesis,
)
from valuation_engine.ai.guards import admit_feature, confidence, safe_narrative, validate_evidence
from valuation_engine.ai.prompts import SYSTEM, TASKS, prompt
from valuation_engine.ai.provider import ProviderUnavailable
from valuation_engine.ai.quarter_package import build_package
from valuation_engine.ai.sources import chunks, retrieve
from valuation_engine.db.schema import (
    AIAnalysisEvent,
    AIAnalysisRun,
    AIAnalystFeature,
    AIAnalystSnapshot,
    AIChallenge,
    AIEvidence,
    AIFeatureEvidence,
    AIProviderCall,
    AIUnsupportedClaim,
    ModelAdjustmentProposal,
)
from valuation_engine.db.store import digest
from valuation_engine.quant.ai_context import context_for

MAX_ATTEMPTS = 2


def event(db, run_id, status, **details):
    db.add(AIAnalysisEvent(analysis_run_id=run_id, status=status, details=details))
    db.flush()


def unsupported(db, run_id, stage, reason, raw):
    db.add(AIUnsupportedClaim(analysis_run_id=run_id, stage=stage, reason=reason, raw_claim=raw))
    db.flush()


def invoke(db, run, provider, stage, payload, response_type):
    exact = prompt(stage, payload, response_type)
    callback = {
        "extract": provider.extract_evidence,
        "synthesize": provider.synthesize_features,
        "challenge": provider.generate_challenge,
    }[stage]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw = {}
        started = datetime.now(UTC).isoformat()
        try:
            package_request = getattr(provider, "request_with_package", None)
            raw = (
                package_request(stage, exact, run.context_json)
                if provider.provider_name == "codex_cli" and package_request is not None
                else callback(exact)
            )
            cli_identity = (
                provider.provider_name
                in {"claude_cli", "gemini_cli", "antigravity_cli", "codex_cli"}
                and provider.settings.get("transport_version") == "CLITransportV1"
                and raw.get("execution_metadata", {}).get("auth_mode")
                == (
                    "chatgpt_subscription"
                    if provider.provider_name == "codex_cli"
                    else "subscription_cli_session"
                )
                and raw.get("execution_metadata", {}).get("requested_model") == provider.model_name
                and raw.get("execution_metadata", {}).get("cli_version")
                == run.settings_json.get("cli_version")
            )
            if (
                provider.provider_name
                in {"claude_cli", "gemini_cli", "antigravity_cli", "codex_cli"}
                and not cli_identity
            ) or (
                provider.provider_name
                not in {"claude_cli", "gemini_cli", "antigravity_cli", "codex_cli"}
                and raw.get("response_model") != provider.model_version
            ):
                raise ValueError("Provider returned an unpinned model version")
            result = response_type.model_validate(raw.get("structured_output"))
            status = "valid"
        except Exception as exc:
            # Do not log exception text/headers: adapters may put credentials in exceptions.
            status = "invalid_or_unavailable"
            error_type = type(exc).__name__
            journal = getattr(provider, "_attempt_journal", None)
            if getattr(journal, "process_state_unknown", False):
                raw["execution_metadata"] = {"failure_kind": "termination_unconfirmed"}
        if provider.provider_name in {"claude_cli", "gemini_cli", "antigravity_cli", "codex_cli"}:
            metadata = raw.setdefault("execution_metadata", {})
            for key, value in provider.settings.items():
                metadata.setdefault(key, value)
            metadata.setdefault("raw_output_hash", None)
            metadata.setdefault(
                "failure_kind",
                "schema_failure"
                if raw.get("structured_output") is not None
                else "provider_unavailable",
            )
            metadata.setdefault(
                "started_at",
                None if metadata.get("failure_kind") == "process_launch_failure" else started,
            )
            metadata.setdefault("completed_at", datetime.now(UTC).isoformat())
            metadata.setdefault("exit_code", None)
            metadata.update(
                retry_count=attempt - 1,
                prompt_version=run.prompt_version,
                schema_version=run.schema_version,
                schema_hash=digest(exact["response_schema"]),
                prompt_hash=digest([stage, exact]),
                source_document_ids=run.source_document_ids,
                source_hashes=[s["source_hash"] for s in run.context_json["sources"]["documents"]],
            )
        db.add(
            AIProviderCall(
                analysis_run_id=run.id,
                stage=stage,
                attempt=attempt,
                exact_prompt=exact,
                request_hash=digest([stage, exact]),
                response_hash=digest(raw) if raw else None,
                raw_output=raw,
                status=status,
            )
        )
        db.flush()
        if status == "valid":
            return result
        event(
            db,
            run.id,
            "provider_attempt_failed",
            stage=stage,
            attempt=attempt,
            error_type=error_type,
        )
        if raw.get("execution_metadata", {}).get("failure_kind") in {
            "quota_limited",
            "authentication_failure",
            "unsupported_client",
            "isolation_contract_failure",
            "ANTIGRAVITY_CLI_PIT_ISOLATION_UNSUPPORTED",
            "PIT_TOOL_OR_PERMISSION_ATTEMPT",
            "CODEX_CLI_PIT_ISOLATION_UNSUPPORTED",
            "termination_unconfirmed",
        }:
            break
    raise ProviderUnavailable("Structured provider call failed after bounded attempts")


def prepare(db, quant_run, raw_dir=None):
    context = context_for(db, quant_run)
    sources = retrieve(db, quant_run.company_id, quant_run.information_cutoff, raw_dir)
    prepared = {"quant_context": context, "sources": sources}
    prepared["quarter_package_manifest"] = build_package(prepared)["manifest"]
    return prepared


def analyze(
    db,
    quant_run,
    provider,
    raw_dir=None,
    refresh=False,
    *,
    prepared_context=None,
    approved_context_hash=None,
):
    if prepared_context is None:
        if approved_context_hash is not None:
            raise ValueError("An approved context hash requires its prepared analysis context")
        prepared = prepare(db, quant_run, raw_dir)
    else:
        if not isinstance(prepared_context, dict):
            raise ValueError("Prepared analysis context must be a mapping")
        if (
            not isinstance(approved_context_hash, str)
            or digest(prepared_context) != approved_context_hash
        ):
            raise ValueError("Prepared analysis context does not match its approved context hash")
        prepared = prepared_context
    context, sources = prepared["quant_context"], prepared["sources"]
    if provider.provider_name in {"claude_cli", "gemini_cli", "antigravity_cli", "codex_cli"}:
        from valuation_engine.ai.validation import QUARTERS

        if context["quarter"] not in QUARTERS:
            raise ProviderUnavailable("M4.1 permits only the seven PM-approved quarters")
    request_hash = digest(
        [
            prepared,
            provider.provider_name,
            provider.model_name,
            provider.model_version,
            provider.settings,
            POLICY_VERSION,
            PROMPT_VERSION,
            SCHEMA_VERSION,
            SYSTEM,
            TASKS,
            Extraction.model_json_schema(),
            Synthesis.model_json_schema(),
            Challenges.model_json_schema(),
        ]
    )
    if not refresh:
        existing = db.scalar(
            select(AIAnalystSnapshot)
            .join(AIAnalysisRun)
            .where(AIAnalysisRun.request_hash == request_hash)
            .order_by(AIAnalystSnapshot.id.desc())
        )
        if existing:
            return existing
    run = AIAnalysisRun(
        company_id=quant_run.company_id,
        quarter=context["quarter"],
        as_of_timestamp=quant_run.forecast_as_of,
        information_cutoff=quant_run.information_cutoff,
        source_document_ids=[s["source_document_id"] for s in sources["documents"]],
        model_provider=provider.provider_name,
        model_name=provider.model_name,
        model_version=provider.model_version,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        policy_version=POLICY_VERSION,
        request_hash=request_hash,
        context_json=prepared,
        settings_json=provider.settings,
    )
    db.add(run)
    db.flush()
    event(db, run.id, "started")
    if not sources["blocks"]:
        event(db, run.id, "missing_source")
        return None
    block_map = {b["block_id"]: b for b in sources["blocks"]}
    evidence, row_ids, dedup = {}, {}, set()
    try:
        for index, batch in enumerate(chunks(sources["blocks"])):
            extracted = invoke(
                db,
                run,
                provider,
                "extract",
                {"cutoff": context["information_cutoff"], "blocks": batch},
                Extraction,
            )
            for item in extracted.evidence:
                valid, reason = validate_evidence(item, block_map)
                # Evidence must come from THIS extraction request, not another source chunk.
                if item.block_id not in {b["block_id"] for b in batch}:
                    valid, reason = None, "block_not_in_current_request"
                if not valid:
                    unsupported(db, run.id, "extract", reason, item.model_dump())
                    continue
                fingerprint = (valid["source_hash"], valid["span_hash"], valid["topic"])
                if fingerprint in dedup:
                    continue
                dedup.add(fingerprint)
                key = f"{index}:{item.key}"
                if key in evidence:
                    unsupported(db, run.id, "extract", "duplicate_evidence_key", item.model_dump())
                    continue
                valid["key"] = key
                row = AIEvidence(
                    analysis_run_id=run.id,
                    evidence_key=key,
                    **{
                        k: valid[k]
                        for k in (
                            "source_document_id",
                            "source_hash",
                            "section",
                            "block_id",
                            "span",
                            "span_hash",
                            "speaker",
                            "topic",
                            "implication",
                        )
                    },
                    published_at=datetime.fromisoformat(valid["published_at"])
                    if valid["published_at"]
                    else None,
                    available_at=datetime.fromisoformat(valid["available_at"]),
                    metadata_json=valid,
                )
                db.add(row)
                db.flush()
                evidence[key], row_ids[key] = valid, row.id
        event(db, run.id, "evidence_extracted", evidence_count=len(evidence))
        if not evidence:
            event(db, run.id, "no_supported_evidence")
            return None
        synthesized = invoke(
            db, run, provider, "synthesize", {"evidence": list(evidence.values())}, Synthesis
        )
        features = {}
        for item in synthesized.features:
            valid, reason = admit_feature(item, evidence)
            if item.feature_name in features:
                valid, reason = None, "duplicate_feature"
            if not valid:
                unsupported(db, run.id, "synthesize", reason, item.model_dump())
                continue
            feature_row = AIAnalystFeature(
                company_id=run.company_id,
                analysis_run_id=run.id,
                **{
                    k: valid[k]
                    for k in (
                        "feature_name",
                        "feature_value",
                        "confidence",
                        "direction",
                        "time_horizon",
                        "evidence_count",
                        "source_document_ids",
                    )
                },
                prompt_version=PROMPT_VERSION,
                model_version=provider.model_version,
                rationale=valid["net_assessment"],
                metadata_json=valid,
            )
            db.add(feature_row)
            db.flush()
            for role in ("supporting_evidence", "contradicting_evidence"):
                for key in valid[role]:
                    db.add(
                        AIFeatureEvidence(
                            feature_id=feature_row.id, evidence_id=row_ids[key], role=role
                        )
                    )
            features[item.feature_name] = valid
        sections = {}
        for item in synthesized.sections:
            if (
                not item.evidence
                or any(k not in evidence for k in item.evidence)
                or not safe_narrative(item.summary)
            ):
                unsupported(db, run.id, "section", "unsupported_section", item.model_dump())
                continue
            sections[item.section] = {
                **item.model_dump(),
                "confidence": confidence([evidence[k] for k in item.evidence]),
                "evidence_ids": [row_ids[k] for k in item.evidence],
            }
        challenge_result = invoke(
            db,
            run,
            provider,
            "challenge",
            {"evidence": list(evidence.values()), "quant_context": context, "features": features},
            Challenges,
        )
        challenges = []
        for item in challenge_result.challenges:
            if (
                not item.evidence
                or any(k not in evidence for k in item.evidence)
                or not safe_narrative(item.description)
            ):
                unsupported(db, run.id, "challenge", "unsupported_challenge", item.model_dump())
                continue
            if item.kind == "anomaly" and item.anomaly_code not in context["anomaly_codes"]:
                unsupported(db, run.id, "challenge", "unknown_quant_anomaly", item.model_dump())
                continue
            if (item.kind == "regime") != (item.affected_model_variable == "regime"):
                unsupported(
                    db, run.id, "challenge", "inconsistent_regime_target", item.model_dump()
                )
                continue
            value = {
                **item.model_dump(),
                "confidence": confidence([evidence[k] for k in item.evidence]),
                "evidence_ids": [row_ids[k] for k in item.evidence],
                "interpretation_status": "evidence_linked_hypothesis_not_verified_causality",
            }
            db.add(
                AIChallenge(
                    analysis_run_id=run.id,
                    kind=item.kind,
                    description=item.description,
                    direction=item.direction,
                    target_variable=item.affected_model_variable,
                    time_horizon=item.time_horizon,
                    evidence_ids=value["evidence_ids"],
                    confidence=value["confidence"],
                    metadata_json=value,
                )
            )
            if item.kind == "adjustment":
                db.add(
                    ModelAdjustmentProposal(
                        company_id=run.company_id,
                        analysis_run_id=run.id,
                        target_model="frozen_M2_Model_A",
                        target_variable=item.affected_model_variable,
                        direction=item.direction,
                        suggested_range_low=None,
                        suggested_range_high=None,
                        confidence=value["confidence"],
                        rationale=item.description,
                        evidence_ids=value["evidence_ids"],
                        status="proposed",
                    )
                )
            challenges.append(value)
        if not features:
            event(db, run.id, "no_supported_features")
            return None
        primary_fields = (
            "demand_momentum",
            "pricing_power",
            "supply_constraint",
            "product_cycle_strength",
            "competition_outlook",
            "customer_financing_quality",
            "working_capital_quality",
            "regulatory_outlook",
            "management_confidence",
            "guidance_visibility",
            "structural_outlook",
        )
        snapshot = AIAnalystSnapshot(
            company_id=run.company_id,
            as_of_timestamp=run.as_of_timestamp,
            analysis_run_id=run.id,
            **{k: features[k]["feature_value"] if k in features else None for k in primary_fields},
            overall_qualitative_confidence=sum(x["confidence"] for x in features.values())
            / len(get_args(FeatureName)),
            prompt_version=PROMPT_VERSION,
            model_version=provider.model_version,
            metadata_json={
                "features": features,
                "missing_features": [k for k in get_args(FeatureName) if k not in features],
                "sections": sections,
                "challenges": challenges,
                "source_coverage": sources["coverage"],
                "guidance_semantic_features": {
                    k: v
                    for k, v in features.items()
                    if k in ("guidance_visibility", "demand_visibility", "management_confidence")
                },
                "combined_credibility_view": {
                    "quant_guidance_accuracy": context["quant_guidance_accuracy"],
                    "ai_credibility_signal": features.get("management_credibility_signal"),
                    "combined_score": None,
                    "status": "research_view_only",
                },
                "human_review_status": "pending",
                "semantic_entailment_status": "not_human_verified",
            },
        )
        db.add(snapshot)
        db.flush()
        event(db, run.id, "completed", snapshot_id=snapshot.id)
        return snapshot
    except ProviderUnavailable:
        event(db, run.id, "provider_unavailable")
        return None
