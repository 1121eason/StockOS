"""Regression cases from adopted review: duplicates, mixed/neutral roles, provenance."""

import copy
import hashlib
import json
from datetime import datetime

import pytest

from valuation_engine.ai import review_revision as revision


def item(key, implication, span="Demand declined from the previous quarter."):
    return {
        "key": key,
        "topic": "demand_momentum",
        "implication": implication,
        "span": span,
        "span_hash": hashlib.sha256(span.encode()).hexdigest(),
        "block_id": key,
        "source_hash": "source",
        "available_at": "2022-08-24T20:21:00+00:00",
    }


@pytest.fixture
def sample():
    evidence = [
        item("a", "negative"),
        item("duplicate", "negative"),
        item("b", "positive", "Data Center grew from the previous quarter."),
        item("c", "mixed", "Revenue rose annually and declined sequentially."),
        item("d", "neutral", "Management issued revenue guidance."),
    ]
    feature = {
        "feature_name": "demand_momentum",
        "feature_value": -0.4,
        "evidence_keys": [e["key"] for e in evidence],
        "evidence_count": 4,
        "supporting_evidence": ["a", "duplicate", "d"],
        "contradicting_evidence": ["b", "c"],
        "confidence": 0.5,
        "net_assessment": "Recent contraction exceeds earlier growth.",
    }
    source_map = {
        "documents": [
            {
                "source_hash": "source",
                "source_url": "https://example.com/second-quarter-fiscal-2023",
            }
        ],
        "blocks": [
            {
                "block_id": e["key"],
                "text": e["span"],
                "source_hash": "source",
                "available_at": e["available_at"],
            }
            for e in evidence
        ],
    }
    return {
        "features": [feature],
        "evidence": evidence,
        "section_drafts": [],
        "rejections": [{"reason": "too_long"}],
    }, source_map


def test_duplicate_keys_are_counted_separately_from_independent_quotes(sample):
    value, _ = sample
    before = copy.deepcopy(value)
    result = revision.evidence_accounting(
        value["features"][0], {e["key"]: e for e in value["evidence"]}
    )
    assert result["raw_citation_occurrences"] == 5
    assert result["admitted_evidence_keys"] == 5
    assert result["unique_quotations"] == 4
    assert result["duplicate_quote_groups"] == [["a", "duplicate"]]
    assert value == before


def test_mixed_and_neutral_are_not_opposition_or_support(sample):
    value, source_map = sample
    before = copy.deepcopy(value)
    result = revision.revise_sample(
        value, source_map, datetime.fromisoformat("2022-08-25T13:30:00+00:00")
    )
    feature = result["features"][0]
    assert feature["review_roles"] == {
        "support": ["a", "duplicate"],
        "opposition": ["b"],
        "mixed": ["c"],
        "context": ["d"],
    }
    assert feature["original_roles"]["support"] == ["a", "duplicate", "d"]
    assert feature["original_wrapper_confidence"] == 0.5
    assert feature["confidence"] is None and feature["feature_value"] is None
    assert result["rejection_accounting"]["raw_rejected_claims"] == 1
    assert not result["promotion_ready"] and result["quality_verdict"] == "UNSCORED"
    assert value == before


@pytest.mark.parametrize("fault", ["quote", "hash", "future", "topic", "count", "unknown", "role"])
def test_bad_source_or_count_never_becomes_a_candidate(sample, fault):
    value, source_map = sample
    if fault == "quote":
        value["evidence"][0]["span"] = "Invented quotation"
    elif fault == "hash":
        value["evidence"][0]["span_hash"] = "wrong"
    elif fault == "future":
        source_map["blocks"][0]["available_at"] = "2022-08-26T00:00:00+00:00"
    elif fault == "topic":
        value["evidence"][0]["topic"] = "pricing_power"
    elif fault == "count":
        value["features"][0]["evidence_count"] = 5
    elif fault == "unknown":
        value["features"][0]["evidence_keys"].append("invented")
    else:
        value["features"][0]["supporting_evidence"] = []
    with pytest.raises(ValueError):
        revision.revise_sample(
            value, source_map, datetime.fromisoformat("2022-08-25T13:30:00+00:00")
        )


def test_history_only_and_unassessed_section_topics_remain_explicit(sample):
    value, source_map = sample
    source_map["documents"].append(
        {"source_hash": "prior", "source_url": "https://example.com/prior-quarter"}
    )
    for block, evidence in zip(source_map["blocks"], value["evidence"], strict=True):
        block["source_hash"] = evidence["source_hash"] = "prior"
    extra = item("other", "neutral", "Customer pricing faces ongoing pressure.")
    extra["topic"] = "pricing_power"
    value["evidence"].append(extra)
    source_map["blocks"].append(
        {
            "block_id": "other",
            "text": extra["span"],
            "source_hash": "source",
            "available_at": extra["available_at"],
        }
    )
    value["section_drafts"] = [
        {"section": "Risks", "summary": "Pricing risk.", "evidence": ["other"]}
    ]
    result = revision.revise_sample(
        value, source_map, datetime.fromisoformat("2022-08-25T13:30:00+00:00")
    )
    assert result["features"][0]["assessment_scope"] == "HISTORICAL_CONTEXT_ONLY"
    assert result["section_drafts"][0]["unassessed_topics"] == ["pricing_power"]


def test_export_rejects_unbound_packet_and_never_overwrites(tmp_path):
    packet, out = tmp_path / "packet", tmp_path / "out"
    packet.mkdir()
    (packet / "manifest.json").write_text(json.dumps({"files": {}, "packet_hash": "untrusted"}))
    with pytest.raises(ValueError, match="Unrecognized"):
        revision.prepare_revision(packet, tmp_path / "context", out)
    assert not out.exists()
    out.mkdir()
    with pytest.raises(ValueError, match="new directory"):
        revision.prepare_revision(packet, tmp_path / "context", out)
    with pytest.raises(ValueError, match="outside"):
        revision.prepare_revision(packet, tmp_path / "context", packet / "nested")


def test_guidance_comparison_uses_same_quarter_actual_and_preserves_forecast():
    context = {
        "information_cutoff": "2022-08-25T13:30:00+00:00",
        "quant_guidance_accuracy": {
            "revenue": {
                "adjustment": "0.03757440",
                "samples": [
                    {
                        "target": "FY2023-Q2",
                        "actual": "6704000000",
                        "actual_fact_ids": [233],
                        "actual_available_at": "2022-08-24T20:21:00+00:00",
                        "guidance": {
                            "midpoint": "8100000000",
                            "available_at": "2022-05-25T20:21:00+00:00",
                        },
                    }
                ],
            }
        },
        "quant_forecasts": [
            {"period_type": "quarter", "id": 2355, "revenue": "6121688988.09523810"}
        ],
    }
    sources = {
        "blocks": [
            {
                "source_document_id": 10,
                "block_id": "outlook",
                "text": "Revenue is expected to be $5.90 billion, plus or minus 2%.",
                "available_at": "2022-08-24T20:21:00+00:00",
            }
        ]
    }
    before = copy.deepcopy(context)
    result = revision.quant_comparison(context, sources)
    from decimal import Decimal

    assert Decimal(result["next_guidance_high"]) == 6018000000
    assert Decimal(result["actual_vs_prior_guidance"]) < 0
    assert Decimal(result["forecast_vs_guidance_high"]) > 0
    assert context == before
    context["quant_guidance_accuracy"]["revenue"]["samples"][0]["actual_available_at"] = (
        "2023-01-01T00:00:00+00:00"
    )
    with pytest.raises(ValueError, match="cutoff"):
        revision.quant_comparison(context, sources)
