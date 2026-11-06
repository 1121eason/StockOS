"""Pure explanation-stage contracts; no provider, model, database or network."""

import copy
import importlib.util
from pathlib import Path

import pytest

from valuation_engine.ai import explanation_stages as stages
from valuation_engine.research.synthesis import canonical_sha, research_binding


@pytest.fixture
def research():
    metric = {
        "value": "120",
        "fact_ids": [10],
        "source_ids": [1],
        "available_at": "2026-08-27T00:00:00Z",
        "formula": "reported",
        "metadata": {"large_lineage": "excluded"},
    }
    current = {
        "quarter": "FY2027-Q2",
        "period_end": "2026-07-26",
        "checkpoint": "2026-10-22T00:00:00Z",
        "information_cutoff": "2026-10-22T00:00:00Z",
        "metrics": {"revenue": metric},
        "regime": {
            "confirmed_regime": "Growth",
            "candidate_regime": "Hypergrowth",
            "transition_status": "STABLE",
            "composite_confidence": ".9",
            "scores": {"demand": ".8"},
            "input_lineage": {"huge": "excluded"},
        },
        "valuation": {
            "status": "available",
            "base": "250",
            "low": "200",
            "high": "300",
            "basis_date": "2026-08-27",
            "cashflows": ["100", "110"],
            "balance_lineage": {"huge": "excluded"},
        },
    }
    previous = copy.deepcopy(current)
    previous.update(quarter="FY2027-Q1", period_end="2026-04-26")
    previous["metrics"]["revenue"]["value"] = "100"
    return {
        "version": "SyntheticV1",
        "ticker": "NVDA",
        "currency": "USD",
        "current": current,
        "previous": previous,
        "sources": [
            {"id": 1, "sha256": "a" * 64, "url": "https://www.sec.gov/current"},
            {"id": 2, "sha256": "b" * 64, "url": "https://www.sec.gov/previous"},
        ],
        "source_database_sha256": "d" * 64,
        "revisions": [
            {
                "target": "FY2027",
                "status": "AVAILABLE",
                "metrics": {"revenue": ".1", "eps": "0", "free_cash_flow": None},
                "future_outcomes": "excluded",
            }
        ],
        "quote": {"price": "999"},
        "price_comparison": {"gap": "999"},
        "future_outcomes": "excluded",
    }


def _request(research):
    return {
        "version": "StockOSAIExplanationRequestV1",
        "ticker": "NVDA",
        "quarter": "FY2027-Q2",
        "checkpoint": research["current"]["checkpoint"],
        "information_cutoff": research["current"]["information_cutoff"],
        "research_binding": research_binding(research),
        "sources": [
            {
                **copy.deepcopy(research["sources"][0]),
                "quarter": "FY2027-Q2",
                "period_scope": "current_quarter",
                "available_at": "2026-08-27T00:00:00Z",
            },
            {
                **copy.deepcopy(research["sources"][1]),
                "quarter": "FY2027-Q1",
                "period_scope": "previous_quarter",
                "available_at": "2026-05-21T00:00:00Z",
            },
        ],
        "source_blocks": [
            {
                "paragraph_id": "1:current",
                "source_id": 1,
                "source_sha256": "a" * 64,
                "text": "Revenue increased. Demand remains uncertain. Supply constraints may reduce sales.",
                "content_kind": "text",
            },
            {
                "paragraph_id": "2:prior",
                "source_id": 2,
                "source_sha256": "b" * 64,
                "text": "Prior-quarter inventory charges reduced reported gross margin.",
                "content_kind": "text",
            },
        ],
        "quant_context": {
            key: copy.deepcopy(research[key])
            for key in ("current", "previous", "revisions", "currency")
        },
    }


@pytest.fixture
def explanation_request(research):
    return _request(research)


@pytest.fixture
def extraction():
    return {
        "evidence": [
            {
                "paragraph_id": "1:current",
                "quote": "Demand remains uncertain.",
                "kind": "fact",
                "topic": "需求",
                "observation": "需求仍有不確定性，需核對後續揭露。",
            }
        ]
    }


def candidate(request):
    constants = {
        key: row["const"]
        for key, row in stages.candidate_schema(request)["properties"].items()
        if "const" in row
    }
    return {
        **constants,
        "sections": [
            {
                "kind": kind,
                "title": kind,
                "claims": [
                    {
                        "kind": "inference",
                        "text": "這是有待核對的研究推論。",
                        "citations": [
                            {"paragraph_id": "1:current", "quote": "Demand remains uncertain."}
                        ],
                    }
                ],
            }
            for kind in stages.SECTION_KINDS
        ],
    }


def test_candidate_schema_is_exact_existing_contract(explanation_request):
    spec = importlib.util.spec_from_file_location(
        "prepare_ai_explanation",
        Path(__file__).resolve().parents[2] / "scripts/prepare_ai_explanation.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert stages.candidate_schema(explanation_request) == module.candidate_schema(
        explanation_request
    )


def test_extraction_is_pure_and_labels_current_and_prior_sources(explanation_request):
    original = copy.deepcopy(explanation_request)
    prompt = stages.extraction_prompt(explanation_request, 1, explanation_request["source_blocks"])
    assert explanation_request == original
    assert prompt["untrusted_data"]["sources"][0]["period_scope"] == "current_quarter"
    assert prompt["untrusted_data"]["sources"][1]["period_scope"] == "previous_quarter"
    assert prompt["untrusted_data"]["source_blocks"] == explanation_request["source_blocks"]
    assert prompt["response_schema"]["properties"]["evidence"]["maxItems"] == 40
    assert "不要把表格" in prompt["task"]
    assert "55" in prompt["task"]
    assert "quote" not in prompt["untrusted_data"]


@pytest.mark.parametrize("index", [0, 21, True, "1"])
def test_extraction_index_does_not_expand_stage_budget(explanation_request, index):
    with pytest.raises(ValueError):
        stages.extraction_prompt(explanation_request, index, explanation_request["source_blocks"])


@pytest.mark.parametrize("fault", ["empty", "duplicate", "foreign", "mutated", "oversized"])
def test_batch_must_be_unchanged_request_blocks_within_text_cap(explanation_request, fault):
    batch = copy.deepcopy(explanation_request["source_blocks"])
    if fault == "empty":
        batch = []
    elif fault == "duplicate":
        batch *= 2
    elif fault == "foreign":
        batch[0]["paragraph_id"] = "other"
    elif fault == "mutated":
        batch[0]["text"] = "Changed text."
    else:
        explanation_request["source_blocks"][0]["text"] = "X" * 18_001
        batch = explanation_request["source_blocks"]
    with pytest.raises(ValueError):
        stages.extraction_prompt(explanation_request, 1, batch)


def test_exact_span_validation_enriches_period_without_scores(explanation_request, extraction):
    original = copy.deepcopy(extraction)
    result = stages.validate_extraction(
        explanation_request, explanation_request["source_blocks"], extraction
    )
    assert extraction == original
    assert result[0]["period_scope"] == "current_quarter"
    assert result[0]["source_quarter"] == "FY2027-Q2"
    assert result[0]["source_sha256"] == "a" * 64
    assert "confidence" not in result[0]
    assert (
        stages.validate_extraction(
            explanation_request, explanation_request["source_blocks"], {"evidence": []}
        )
        == []
    )


@pytest.mark.parametrize(
    "fault",
    [
        "bad_quote",
        "other_chunk",
        "extra_score",
        "kind",
        "empty_topic",
        "duplicate",
        "too_many",
        "long_quote",
        "long_words",
    ],
)
def test_extraction_rejects_untraceable_or_unbounded_outputs(
    explanation_request, extraction, fault
):
    row = extraction["evidence"][0]
    batch = explanation_request["source_blocks"][:1]
    if fault == "bad_quote":
        row["quote"] = "Demand is guaranteed."
    elif fault == "other_chunk":
        row.update(
            paragraph_id="2:prior",
            quote="Prior-quarter inventory charges reduced reported gross margin.",
        )
    elif fault == "extra_score":
        row["confidence"] = 0.99
    elif fault == "kind":
        row["kind"] = "approved"
    elif fault == "empty_topic":
        row["topic"] = " "
    elif fault == "duplicate":
        extraction["evidence"] *= 2
    elif fault == "too_many":
        extraction["evidence"] *= 41
    elif fault == "long_quote":
        row["quote"] = "X" * 551
        batch[0]["text"] = row["quote"]
    else:
        row["quote"] = " ".join(["word"] * 56)
        batch[0]["text"] = row["quote"]
    with pytest.raises(ValueError):
        stages.validate_extraction(explanation_request, batch, extraction)


def test_quant_allowlist_excludes_prices_outcomes_scores_and_large_lineage(explanation_request):
    explanation_request["quant_context"].update(quote={"price": "999"}, future_outcomes="excluded")
    original = copy.deepcopy(explanation_request)
    compact = stages.compact_quant_context(explanation_request)
    assert explanation_request == original
    text = str(compact)
    assert "999" not in text
    assert "excluded" not in text
    assert "scores" not in text and "confidence" not in text
    assert compact["current"]["metrics"]["revenue"]["value"] == "120"
    assert compact["previous"]["metrics"]["revenue"]["value"] == "100"
    assert compact["current"]["valuation"]["base"] == "250"
    assert compact["revisions"][0]["metrics"]["free_cash_flow"] is None


def test_synthesis_requires_admitted_evidence_and_preserves_identity(
    explanation_request, extraction
):
    evidence = stages.validate_extraction(
        explanation_request, explanation_request["source_blocks"], extraction
    )
    prompt = stages.synthesis_prompt(explanation_request, evidence)
    assert prompt["response_schema"] == stages.candidate_schema(explanation_request)
    assert prompt["untrusted_data"]["request_sha256"] == canonical_sha(explanation_request)
    assert "invalidation_conditions" in prompt["task"]
    assert "不是未來12個月目標價" in prompt["task"]
    assert "confidence" not in str(prompt["untrusted_data"])
    with pytest.raises(ValueError):
        stages.synthesis_prompt(explanation_request, [])
    evidence[0]["period_scope"] = "previous_quarter"
    with pytest.raises(ValueError, match="provenance"):
        stages.synthesis_prompt(explanation_request, evidence)


def test_final_candidate_remains_unapproved_and_reuses_admitted_spans(
    research, explanation_request, extraction
):
    evidence = stages.validate_extraction(
        explanation_request, explanation_request["source_blocks"], extraction
    )
    value = candidate(explanation_request)
    original = copy.deepcopy(value)
    assert (
        stages.validate_final(research, explanation_request, value, evidence=evidence) == original
    )
    assert value == original
    assert "promotion_ready" not in value
    value["sections"][0]["claims"][0]["citations"][0]["quote"] = "Revenue increased."
    with pytest.raises(ValueError, match="not admitted"):
        stages.validate_final(research, explanation_request, value, evidence=evidence)


@pytest.mark.parametrize("fault", ["missing_section", "wrong_quarter", "score", "unknown_quote"])
def test_final_guard_inherits_existing_candidate_rejections(research, explanation_request, fault):
    value = candidate(explanation_request)
    if fault == "missing_section":
        value["sections"].pop()
    elif fault == "wrong_quarter":
        value["quarter"] = "FY2023-Q2"
    elif fault == "score":
        value["confidence"] = 0.9
    else:
        value["sections"][0]["claims"][0]["citations"][0]["quote"] = "Invented text."
    with pytest.raises(ValueError):
        stages.validate_final(research, explanation_request, value)


def challenge():
    return {
        "summary": "這是模型反證檢查，仍需真人審查。",
        "issues": [
            {
                "category": "quotation_context",
                "severity": "review",
                "text": "需核對引文與因果關係。",
                "citations": [{"paragraph_id": "1:current", "quote": "Demand remains uncertain."}],
            }
        ],
        "unassessed_topics": ["未提供獨立競爭者資料"],
        "human_review_required": True,
        "promotion_ready": False,
    }


def test_challenge_supplies_full_referenced_paragraph_and_never_approves(explanation_request):
    value = candidate(explanation_request)
    prompt = stages.challenge_prompt(explanation_request, value)
    assert len(prompt["untrusted_data"]["referenced_source_blocks"]) == 1
    assert (
        prompt["untrusted_data"]["referenced_source_blocks"][0]["text"]
        == explanation_request["source_blocks"][0]["text"]
    )
    assert "不是真人" in prompt["task"]
    response = challenge()
    original = copy.deepcopy(response)
    assert stages.validate_challenge(explanation_request, response) == original
    assert response == original
    value["quarter"] = "FY2023-Q2"
    with pytest.raises(ValueError, match="identity"):
        stages.challenge_prompt(explanation_request, value)


@pytest.mark.parametrize(
    "fault",
    [
        "approve",
        "fake_bool",
        "bad_quote",
        "unknown_block",
        "extra_score",
        "too_many",
        "bad_category",
        "bad_severity",
    ],
)
def test_challenge_rejects_score_approval_and_invalid_citations(explanation_request, fault):
    value = challenge()
    if fault == "approve":
        value["promotion_ready"] = True
    elif fault == "fake_bool":
        value["human_review_required"] = 1
    elif fault == "bad_quote":
        value["issues"][0]["citations"][0]["quote"] = "Invented text."
    elif fault == "unknown_block":
        value["issues"][0]["citations"][0]["paragraph_id"] = "foreign"
    elif fault == "extra_score":
        value["score"] = 3
    elif fault == "too_many":
        value["issues"] *= 25
    elif fault == "bad_category":
        value["issues"][0]["category"] = "PASS"
    else:
        value["issues"][0]["severity"] = "APPROVED"
    with pytest.raises(ValueError):
        stages.validate_challenge(explanation_request, value)


def test_missing_information_can_be_marked_without_inventing_citation(explanation_request):
    response = challenge()
    response["issues"][0].update(category="coverage_gap", citations=[])
    assert stages.validate_challenge(explanation_request, response)["promotion_ready"] is False
