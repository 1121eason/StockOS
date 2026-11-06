"""Versioned, evidence-gated acceptance checks for a single PIT quarter."""

import hashlib
from collections import Counter
from datetime import datetime
from typing import get_args

from valuation_engine.ai.contracts import MAX_EVIDENCE_WORDS, FeatureName
from valuation_engine.ai.quarter_package import build_package

QUARANTINABLE_REASONS = frozenset(
    {
        "unsupported_speaker",
        "unsupported_speaker_role",
        "evidence_span_too_long",
        "duplicate_evidence_key",
        "missing_or_unknown_evidence",
        "direction_unsupported",
        "unverified_numeric_or_prohibited_narrative",
        "evidence_topic_mismatch",
        "duplicate_feature",
        "unsupported_section",
        "unsupported_challenge",
        "unknown_quant_anomaly",
        "inconsistent_regime_target",
    }
)


def assess_single_quarter(
    run, snapshot, calls, evidence, features, challenges, rejected, expected_quarter="FY2023-Q2"
):
    """Accept only a complete, supported snapshot; isolated benign rejects are audit-only."""
    blockers: list[str] = []
    if snapshot is None:
        blockers.append("completed_snapshot_missing")
    if not calls or any(call.status != "valid" for call in calls):
        blockers.append("provider_calls_incomplete")
    if run.quarter != expected_quarter:
        blockers.append("expected_quarter_mismatch")

    prepared = run.context_json
    try:
        package = build_package(prepared)
        if package["manifest"] != prepared.get("quarter_package_manifest"):
            blockers.append("quarter_package_manifest_mismatch")
    except (KeyError, TypeError, ValueError):
        package = None
        blockers.append("quarter_package_invalid")
    context = prepared.get("quant_context", {})
    source_docs = {d["source_document_id"]: d for d in prepared.get("sources", {}).get("documents", [])}
    source_blocks = {
        b["block_id"]: b for b in prepared.get("sources", {}).get("blocks", [])
    }
    if package is not None:
        if set(run.source_document_ids) != set(source_docs):
            blockers.append("source_set_mismatch")
        cutoff = datetime.fromisoformat(run.information_cutoff.isoformat())
        for item in evidence:
            doc = source_docs.get(item.source_document_id)
            block = source_blocks.get(item.block_id)
            if (
                doc is None
                or block is None
                or item.source_hash != doc["source_hash"]
                or item.source_hash != block["source_hash"]
                or item.span not in block["text"]
                or item.span_hash != hashlib.sha256(item.span.encode()).hexdigest()
                or item.available_at > cutoff
                or item.available_at != datetime.fromisoformat(block["available_at"])
            ):
                blockers.append("admitted_evidence_pit_or_span_violation")
                break
            attribution = item.metadata_json
            if attribution.get("speaker_status") == "verified":
                if not item.speaker or item.speaker != block.get("speaker"):
                    blockers.append("admitted_speaker_not_verified")
                    break
            elif attribution.get("speaker_status") != "unknown" or item.speaker is not None:
                blockers.append("admitted_speaker_status_invalid")
                break
            role = attribution.get("speaker_role")
            if role is not None and role != block.get("speaker_role"):
                blockers.append("admitted_speaker_role_not_verified")
                break

    admitted_keys = {item.evidence_key for item in evidence}
    admitted_ids = {item.id for item in evidence}
    feature_names = [item.feature_name for item in features]
    all_feature_names = set(get_args(FeatureName))
    missing = set(snapshot.metadata_json.get("missing_features", [])) if snapshot else set()
    snapshot_feature_names = (
        set(snapshot.metadata_json.get("features", {})) if snapshot is not None else set()
    )
    if (
        len(feature_names) != len(set(feature_names))
        or set(feature_names) != snapshot_feature_names
        or set(feature_names) & missing
        or set(feature_names) | missing != all_feature_names
        or len(missing) != len(snapshot.metadata_json.get("missing_features", []))
    ):
        blockers.append("feature_schema_coverage_incomplete")
    if snapshot:
        for name in (
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
        ):
            if name in missing and getattr(snapshot, name) is not None:
                blockers.append("missing_feature_projection_not_null")
                break
    for item in features:
        feature_evidence = set(item.metadata_json.get("evidence_keys", []))
        if not feature_evidence or not feature_evidence <= admitted_keys:
            blockers.append("feature_uses_unadmitted_evidence")
            break
    kinds = {item.kind for item in challenges}
    if not {"upside", "downside", "regime"} <= kinds:
        blockers.append("mandatory_challenge_missing")
    anomaly_codes = set(context.get("anomaly_codes", []))
    if anomaly_codes and not any(
        item.kind == "anomaly" and item.metadata_json.get("anomaly_code") in anomaly_codes
        for item in challenges
    ):
        blockers.append("applicable_anomaly_challenge_missing")
    for item in challenges:
        if (
            not item.evidence_ids
            or not set(item.evidence_ids) <= admitted_ids
            or set(item.metadata_json.get("evidence_ids", [])) != set(item.evidence_ids)
        ):
            blockers.append("challenge_uses_unadmitted_evidence")
            break
    if snapshot:
        for section in snapshot.metadata_json.get("sections", {}).values():
            section_evidence = set(section.get("evidence_ids", []))
            if not section_evidence or not section_evidence <= admitted_ids:
                blockers.append("section_uses_unadmitted_evidence")
                break

    rejection_counts = Counter(item.reason for item in rejected)
    for item in rejected:
        if item.reason not in QUARANTINABLE_REASONS:
            blockers.append("non_quarantinable_rejection:" + item.reason)
            continue
        if item.reason == "evidence_span_too_long":
            raw = item.raw_claim if isinstance(item.raw_claim, dict) else {}
            block = source_blocks.get(raw.get("block_id"))
            span = raw.get("span")
            if (
                block is None
                or not isinstance(span, str)
                or span not in block["text"]
                or len(span.split()) <= MAX_EVIDENCE_WORDS
                or datetime.fromisoformat(block["available_at"]) > run.information_cutoff
            ):
                blockers.append("overlong_rejection_not_verified")
            if any(
                raw.get("block_id") == admitted.block_id and span == admitted.span
                for admitted in evidence
            ):
                blockers.append("rejected_span_reentered_formal_evidence")
        if item.reason in {"unsupported_speaker", "unsupported_speaker_role"}:
            raw = item.raw_claim
            block = source_blocks.get(raw.get("block_id"))
            if (
                block is None
                or not raw.get("span")
                or raw["span"] not in block["text"]
                or datetime.fromisoformat(block["available_at"]) > run.information_cutoff
            ):
                blockers.append("rejected_speaker_candidate_pit_violation")
            if item.reason == "unsupported_speaker":
                status = raw.get("speaker_status")
                invalid_attribution = block is None or (
                    status == "verified" and raw.get("speaker") != block.get("speaker")
                ) or (status == "unknown" and raw.get("speaker") is not None) or status not in {
                    "verified",
                    "unknown",
                }
            else:
                invalid_attribution = (
                    block is None
                    or raw.get("speaker_role") is None
                    or raw.get("speaker_role") != block.get("speaker_role")
                )
            if not invalid_attribution:
                blockers.append("speaker_rejection_reason_inconsistent")
            if any(
                raw.get("block_id") == admitted.block_id and raw.get("span") == admitted.span
                for admitted in evidence
            ):
                blockers.append("rejected_attribution_reentered_formal_evidence")

    return {
        "gate": "PASS" if not blockers else "FAIL",
        "blockers": sorted(set(blockers)),
        "quarantined_rejections": sum(rejection_counts.values()),
        "rejection_reasons": dict(sorted(rejection_counts.items())),
        "formal_evidence_count": len(evidence),
        "feature_count": len(features),
        "challenge_kinds": sorted(kinds),
        "package_hash": prepared.get("quarter_package_manifest", {}).get("package_hash"),
    }
