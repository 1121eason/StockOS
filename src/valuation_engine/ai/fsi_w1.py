"""Approved prospective SEC/IR protocol and offline input preparation.

This module has no provider, database, network or execution entry point. Hashes
bind supplied assertions; they do not authenticate historical publication.
"""

import copy
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

from valuation_engine.ai import experiment_prompts
from valuation_engine.ai.contracts import Challenges, Extraction, Synthesis
from valuation_engine.ai.sources import blocks, chunks

REFERENCE_SHA = "0d71b713d64deccfbf1f77614dbea4bed8d63fe1"
PROTOCOL_VERSION = "FSIS2ProspectiveProtocolV1"
PACKAGE_VERSION = "FSISECIRPackageV1"
QUARTERS = (
    "FY2023-Q2",
    "FY2023-Q3",
    "FY2024-Q1",
    "FY2024-Q2",
    "FY2025-Q4",
    "FY2026-Q1",
    "FY2027-Q2",
)
SOURCE_KINDS = {"Earnings Release", "SEC primary filing", "SEC exhibit"}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def timestamp(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name}: explicit timezone-aware timestamp required")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name}: invalid timestamp") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{name}: explicit timezone required")
    return result.astimezone(UTC)


def protocol():
    """Freeze the actual prospective B/C text and schemas, never historical V6."""
    common = experiment_prompts.SYSTEM.replace(experiment_prompts.FSI_RUBRIC, "").strip()
    methods = {}
    for method in ("B", "C"):
        system = common + ("\n\n" + experiment_prompts.FSI_RUBRIC if method == "C" else "")
        methods[method] = {
            "prompt_version": "S2ExperimentalPromptV1-" + method,
            "system": system,
            "tasks": dict(experiment_prompts.TASKS),
            "response_schemas": {
                "extract": Extraction.model_json_schema(),
                "synthesize": Synthesis.model_json_schema(),
                "challenge": Challenges.model_json_schema(),
            },
        }
    result = {
        "protocol_version": PROTOCOL_VERSION,
        "reference_source_sha": REFERENCE_SHA,
        "decisions": ["D01", "D02", "D03"],
        "decision_status": "USER_APPROVED_OFFLINE_W1_ONLY",
        "scope": "NVDA_SEC_IR_ADVISORY_ONLY",
        "historical_v6_reproduction": False,
        "policy_version": "AIAnalystPolicyV1",
        "schema_version": "FeatureSchemaV1",
        "guard_version": "Guard_G_Strict",
        "candidate_format_version": 2,
        "methods": methods,
        "only_method_difference": "FSI_RUBRIC system extension; tasks, roles and schemas shared",
        "shared_budget": {
            "chunk_characters": 18000,
            "attempts_per_method": 22,
            "attempts_per_pair": 44,
            "extract_timeout_seconds": 180,
            "synthesize_timeout_seconds": 600,
            "challenge_timeout_seconds": 600,
            "outer_retries": 0,
        },
        "review_rule": {
            "version": "FSIS2BlindRubricV1",
            "hard_gates": [
                "exact_quotes_and_no_unresolved_material_unsupported_claim",
                "zero_illegal_admissions",
            ],
            "quality_dimensions": ["dispute_stability", "insight_depth", "challenge_quality"],
            "scale": [0, 1, 2, 3],
            "anchors": {
                "0": "Missing, materially misunderstood or unsupported",
                "1": "Partial relevant evidence; key causality, qualifiers or counterevidence missing",
                "2": "Main conclusion supported; facts and assumptions distinguished; disputes addressed",
                "3": "Score two plus supported alternatives, counterevidence and failure conditions; stability needs valid repeats",
            },
            "independent_reviewers": 2,
            "blinding": "X/Y labels; no method or model labels; retain full sources, rejections and missingness",
            "disagreement": "third_person_adjudication_required",
            "missing_repeat": "UNASSESSED_NO_COMPLETE_TOTAL",
            "both_methods_must_pass_hard_gates": True,
            "c_minimum_each": 2,
            "c_must_be_noninferior_each": True,
            "c_strictly_better_dimensions": 2,
            "unblinding": "after_reviews_and_adjudication_are_hash_bound",
            "missing_scores": "UNASSESSED_NOT_ZERO_NO_COMPLETE_TOTAL",
            "total": "descriptive_sum_of_three_adjudicated_dimensions_only",
            "result_scope": "Q2_exploratory_only_not_formal_promotion",
        },
        "additional_repeat_budget_authorized": False,
        "live_authorized": False,
        "quality_verdict": "UNSCORED",
        "winner": None,
        "promotion_ready": False,
    }
    return {**result, "protocol_hash": digest(result)}


def validate_protocol(value):
    if canonical(value) != canonical(protocol()):
        raise ValueError("Protocol differs from the approved prospective text or rules")


def source_url(value, kind):
    if not isinstance(value, str):
        raise ValueError("Official source URL required")
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise ValueError("Invalid source URL") from None
    if (
        url.scheme != "https"
        or url.username
        or url.password
        or port not in (None, 443)
        or url.fragment
        or any(c.isspace() for c in value)
    ):
        raise ValueError("Official HTTPS URL without credentials required")
    if kind in {"SEC primary filing", "SEC exhibit"}:
        valid = url.hostname in {"sec.gov", "www.sec.gov"} and url.path.startswith(
            "/Archives/edgar/data/1045810/"
        )
    else:
        valid = url.hostname in {"nvidianews.nvidia.com", "investor.nvidia.com"}
    if not valid:
        raise ValueError("Source URL is outside the approved NVIDIA SEC/IR scope")


def build_package(quant_context, documents, source_contents):
    """Reparse ALL selected bytes; no arbitrary source truncation or time filling."""
    if not isinstance(quant_context, dict) or not isinstance(source_contents, dict):
        raise ValueError("Explicit context and content mapping required")
    context = copy.deepcopy(quant_context)
    if context.get("quarter") not in QUARTERS:
        raise ValueError("Quarter outside the seven-quarter panel")
    cutoff = timestamp(context.get("information_cutoff"), "information_cutoff")
    if not isinstance(context.get("anomaly_codes"), list):
        raise ValueError("Explicit anomaly codes required")
    if not isinstance(documents, list) or not documents or len(documents) > 4:
        raise ValueError("Select one to four complete SEC/IR documents")
    seen: set[int] = set()
    parsed: list[dict] = []
    removed: list[dict] = []
    metadata: list[dict] = []
    counts = {"release": 0, "filing": 0}
    for original in documents:
        if not isinstance(original, dict):
            raise ValueError("Document metadata must be an object")
        doc = copy.deepcopy(original)
        sid, sha, kind = (
            doc.get("source_document_id"),
            doc.get("source_hash"),
            doc.get("document_type"),
        )
        if type(sid) is not int or sid <= 0 or sid in seen:
            raise ValueError("Duplicate or invalid source identity")
        seen.add(sid)
        if (
            not isinstance(kind, str)
            or kind not in SOURCE_KINDS
            or type(doc.get("tier")) is not int
            or doc["tier"] != 1
        ):
            raise ValueError("Document is outside the SEC/IR limited scope")
        source_url(doc.get("source_url"), kind)
        if not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha):
            raise ValueError("Invalid content hash")
        content = source_contents.get(sha)
        if not isinstance(content, bytes) or hashlib.sha256(content).hexdigest() != sha:
            raise ValueError("Source bytes do not match the content hash")
        available = timestamp(doc.get("available_at"), "available_at")
        published = (
            timestamp(doc["published_at"], "published_at")
            if doc.get("published_at") is not None
            else None
        )
        if (
            available > cutoff
            or available < cutoff - timedelta(days=200)
            or (published is not None and published > available)
        ):
            raise ValueError("Source time is outside the cutoff/lookback or precedes publication")
        group = "release" if kind == "Earnings Release" else "filing"
        counts[group] += 1
        if counts[group] > 2:
            raise ValueError("At most two releases and two filings are permitted")
        derived, exclusions = blocks(
            SimpleNamespace(id=sid, content_hash=sha, document_type=kind), content
        )
        if not derived:
            raise ValueError("Selected document has no eligible narrative; do not silently omit it")
        doc["block_count"] = len(derived)
        doc["published_at"] = original.get("published_at")  # Unknown remains unknown.
        metadata.append(doc)
        parsed.extend(
            {**b, **{k: doc[k] for k in ("published_at", "available_at", "tier")}} for b in derived
        )
        removed.extend({"source_document_id": sid, **r} for r in exclusions)
    if set(source_contents) != {d["source_hash"] for d in metadata}:
        raise ValueError("Source bytes must match the exact selected document set")
    prepared = {
        "quant_context": context,
        "sources": {
            "documents": metadata,
            "blocks": parsed,
            "excluded_blocks": removed,
            "coverage": {"scope": "SEC_IR_ONLY", "official_call_status": "NOT_IN_ACCEPTED_SCOPE"},
        },
    }
    result = {
        "package_version": PACKAGE_VERSION,
        "prepared": prepared,
        "classification": "OFFLINE_RECONSTRUCTION_INPUTS",
        "source_authenticity": "UNVERIFIED",
        "historical_availability": "UNVERIFIED",
        "model_identity": "UNVERIFIED",
        "historical_oos": False,
        "formal_decision": "withheld",
        "live_calls": 0,
    }
    return {**result, "package_hash": digest(result)}


def validate_package(value, source_contents):
    try:
        expected = build_package(
            value["prepared"]["quant_context"],
            value["prepared"]["sources"]["documents"],
            source_contents,
        )
    except (KeyError, TypeError):
        raise ValueError("Malformed source package") from None
    if canonical(value) != canonical(expected):
        raise ValueError("Package integrity or scope mismatch")


def offline_plan(package, source_contents):
    validate_package(package, source_contents)
    frozen = protocol()
    batch_count = len(list(chunks(package["prepared"]["sources"]["blocks"])))
    attempts = batch_count + 2
    return {
        "protocol_hash": frozen["protocol_hash"],
        "package_hash": package["package_hash"],
        "quarter": package["prepared"]["quant_context"]["quarter"],
        "extraction_chunks": batch_count,
        "planned_attempts_per_method": attempts,
        "planned_attempts_per_pair": 2 * attempts,
        "budget_status": "WITHIN_SINGLE_PAIR_CAP" if attempts <= 22 else "BLOCKED_CALL_CAP",
        "input_status": "BYTES_AND_STRUCTURE_VERIFIED_ONLY",
        "live_status": "BLOCKED_NOT_AUTHORIZED_NOT_RUNTIME_VERIFIED",
        "quality_verdict": "UNSCORED",
        "winner": None,
        "promotion_ready": False,
        "additional_repeats_authorized": False,
        "model_calls": 0,
    }
