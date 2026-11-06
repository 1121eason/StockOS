"""Deterministic evidence admission and wrapper confidence; no model self-confidence."""

import hashlib
import re

from valuation_engine.ai.contracts import MAX_EVIDENCE_WORDS
from valuation_engine.ai.sources import INJECTION, PRICE

NUMERIC = re.compile(
    r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand|million|billion|percent)\b",
    re.I,
)
ACTION = re.compile(
    r"\b(?:buy|sell|hold) (?:the )?(?:stock|shares)|opportunity score|target allocation|fair value|target price",
    re.I,
)


def safe_narrative(value):
    # V1 deliberately forbids generated financial numeric prose; numbers live in exact spans/Quant.
    return not (
        NUMERIC.search(value)
        or INJECTION.search(value)
        or PRICE.search(value)
        or ACTION.search(value)
    )


def validate_evidence(draft, block_map):
    block = block_map.get(draft.block_id)
    if block is None:
        return None, "unknown_or_future_block"
    if draft.span not in block["text"]:
        return None, "span_not_in_source"
    if len(draft.span.split()) > MAX_EVIDENCE_WORDS:
        return None, "evidence_span_too_long"
    if INJECTION.search(draft.span) or PRICE.search(draft.span):
        return None, "unsafe_source_span"
    if draft.speaker_status == "verified":
        if not draft.speaker or draft.speaker != block.get("speaker"):
            return None, "unsupported_speaker"
    elif draft.speaker is not None:
        return None, "unsupported_speaker"
    if draft.speaker_role is not None and draft.speaker_role != block.get("speaker_role"):
        return None, "unsupported_speaker_role"
    return {
        **draft.model_dump(),
        **{
            k: block[k]
            for k in (
                "source_document_id",
                "source_hash",
                "section",
                "available_at",
                "published_at",
                "tier",
            )
        },
        "span_hash": hashlib.sha256(draft.span.encode()).hexdigest(),
    }, None


def confidence(items, contradictory=()):
    if not items:
        return 0.0
    # The same quote copied into another source is not independent evidence.
    unique: dict[str, dict] = {}
    for item in sorted(
        items,
        key=lambda x: (
            x.get("span_hash", x.get("key", "")),
            x.get("source_hash", x.get("topic", "")),
            x.get("block_id", ""),
        ),
    ):
        span_h = item.get("span_hash", item.get("key", ""))
        unique.setdefault(span_h, item)
    items = list(unique.values())
    distinct = {(x.get("source_hash", ""), x.get("block_id", "")) for x in items}
    source_count = len({x.get("source_hash", "") for x in items})
    statement_weights = {"reported_fact": 0.95, "management_statement": 0.8, "risk_disclosure": 0.65}
    certainty_weights = {"explicit": 1, "qualified": 0.8, "ambiguous": 0.5}
    base = sum(
        statement_weights.get(x.get("statement_type", "reported_fact"), 0.8)
        * certainty_weights.get(x.get("certainty", "explicit"), 1)
        * (1 if x.get("tier", 1) == 1 else 0.9)
        for x in items
    ) / len(items)
    count_factor = 0.65 if len(distinct) == 1 else 0.85 if source_count == 1 else 0.95
    cont_hashes = {x.get("span_hash", x.get("key", "")) for x in contradictory}
    contradiction = min(0.5, len(cont_hashes) / len(items))
    return round(base * count_factor * (1 - contradiction), 8)


def admit_feature(draft, evidence):
    ids = draft.supporting_evidence + draft.contradicting_evidence
    if not ids or any(k not in evidence for k in ids):
        return None, "missing_or_unknown_evidence"
    if not safe_narrative(draft.net_assessment):
        return None, "unverified_numeric_or_prohibited_narrative"
    if any(evidence[k]["topic"] != draft.feature_name for k in ids):
        return None, "evidence_topic_mismatch"
    expected = (
        "positive" if draft.feature_value > 0 else "negative" if draft.feature_value < 0 else None
    )
    if expected and not any(
        evidence[k]["implication"] in (expected, "mixed") for k in draft.supporting_evidence
    ):
        return None, "direction_unsupported"
    # Do not let the model suppress a conflicting observation from Pass 1.
    opposing = (
        "negative" if expected == "positive" else "positive" if expected == "negative" else "mixed"
    )
    auto = [
        k
        for k, e in evidence.items()
        if e["topic"] == draft.feature_name and e["implication"] in (opposing, "mixed")
    ]
    contradict = sorted(set(draft.contradicting_evidence + auto))
    support = sorted(set(draft.supporting_evidence) - set(contradict))
    all_ids = sorted(set(ids + contradict))
    items = [evidence[k] for k in all_ids]
    return {
        **draft.model_dump(),
        "supporting_evidence": support,
        "contradicting_evidence": contradict,
        "evidence_keys": all_ids,
        "confidence": confidence(items, [evidence[k] for k in contradict]),
        "direction": "positive_is_favorable",
        "evidence_count": len({e["span_hash"] for e in items}),
        "source_document_ids": sorted({e["source_document_id"] for e in items}),
    }, None
