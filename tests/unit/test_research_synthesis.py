"""Synthetic boundary tests; no model calls, database or semantic acceptance."""

import copy
import hashlib
import json

import pytest

from valuation_engine.research.synthesis import (
    AI_VERSION,
    SECTION_KINDS,
    attach_synthesis,
    canonical_sha,
    research_binding,
    summarize,
    validate_candidate,
)


@pytest.fixture
def research():
    return {
        "version": "SyntheticResearchV1",
        "ticker": "NVDA",
        "currency": "USD",
        "source_database_sha256": "d" * 64,
        "current": {
            "quarter": "FY2027-Q2",
            "checkpoint": "2026-08-27T13:30:00+00:00",
            "information_cutoff": "2026-08-27T13:30:00+00:00",
            "metrics": {
                "revenue": {"value": "120", "source_ids": [1]},
                "net_income": {"value": "0", "source_ids": [1]},
                "fcf": {"value": "-5", "source_ids": [1]},
            },
            "valuation": {"status": "available", "base": "-2", "low": "-4", "high": "0"},
            "regime": {"confirmed_regime": "Growth", "candidate_regime": "Hypergrowth"},
        },
        "previous": {
            "quarter": "FY2027-Q1",
            "metrics": {
                "revenue": {"value": "100"},
                "net_income": {"value": "-2"},
            },
        },
        "revisions": [{"target": "FY2027", "status": "AVAILABLE", "metrics": {"revenue": ".1"}}],
        "sources": [{"id": 1, "sha256": "a" * 64, "url": "https://www.sec.gov/synthetic"}],
    }


@pytest.fixture
def explanation_request(research):
    return {
        "version": "StockOSAIExplanationRequestV1",
        "research_binding": research_binding(research),
        "ticker": research["ticker"],
        **{k: research["current"][k] for k in ("quarter", "checkpoint", "information_cutoff")},
        "source_blocks": [
            {
                "paragraph_id": "1:p1",
                "source_id": 1,
                "source_sha256": "a" * 64,
                "text": "Revenue increased. Demand remains uncertain. This is synthetic.",
            }
        ],
    }


@pytest.fixture
def candidate(explanation_request):
    return {
        "version": AI_VERSION,
        "request_sha256": canonical_sha(explanation_request),
        **{
            k: explanation_request[k]
            for k in ("research_binding", "ticker", "quarter", "checkpoint", "information_cutoff")
        },
        "sections": [
            {
                "kind": kind,
                "title": kind,
                "claims": [
                    {
                        "kind": "inference",
                        "text": "Synthetic unreviewed interpretation.",
                        "citations": [
                            {"paragraph_id": "1:p1", "quote": "Demand remains uncertain."}
                        ],
                    }
                ],
            }
            for kind in SECTION_KINDS
        ],
    }


def test_binding_ignores_quotes_and_clocks_but_binds_all_research_inputs(research):
    expected = research_binding(research)
    view = copy.deepcopy(research)
    view.update(quote={"price": "999"}, price_comparison={"gap": "99"}, verified_at="new-clock")
    view["synthesis"] = {"ignored": True}
    assert research_binding(view) == expected
    for key in ("current", "previous", "revisions", "sources", "source_database_sha256"):
        changed = copy.deepcopy(research)
        if key == "current":
            changed[key]["valuation"]["base"] = "100"
        elif key == "previous":
            changed[key]["quarter"] = "FY2026-Q4"
        elif key == "revisions":
            changed[key][0]["metrics"]["revenue"] = ".2"
        elif key == "sources":
            changed[key][0]["sha256"] = "b" * 64
        else:
            changed[key] = "e" * 64
        assert research_binding(changed) != expected


def test_quant_summary_is_readonly_preserves_missing_zero_negative_and_no_trade(research):
    before = copy.deepcopy(research)
    result = summarize(research)
    assert research == before
    assert result["status"] == "quant_only"
    assert result["financial_summary"][0]["change_ratio"] == "0.2"
    metrics = {r["metric"]: r for r in result["financial_summary"]}
    assert metrics["net_income"]["current"] == "0"
    assert metrics["net_income"]["change_ratio"] is None
    assert metrics["fcf"]["current"] == "-5"
    assert metrics["capex"]["current"] is None
    assert result["valuation_summary"]["base"] == "-2"
    assert (
        result["decision_ready"]
        is result["promotion_ready"]
        is result["affects_valuation"]
        is False
    )
    assert "equity_weight" not in result


def test_valid_citations_are_displayed_without_changing_baseline_or_approving(
    research, explanation_request, candidate
):
    original = copy.deepcopy((research, explanation_request, candidate))
    sections = validate_candidate(research, explanation_request, candidate)
    result = summarize(
        research,
        ai={"status": "candidate_pending_review", "reason": "pending", "sections": sections},
    )
    assert result["status"] == "candidate_pending_review"
    assert result["decision_ready"] is False
    assert (
        sections[0]["claims"][0]["citations"][0]["paragraph"]
        == explanation_request["source_blocks"][0]["text"]
    )
    assert (research, explanation_request, candidate) == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "OldProtocol"),
        ("quarter", "FY2023-Q2"),
        ("ticker", "OTHER"),
        ("checkpoint", "2026-08-28T13:30:00+00:00"),
        ("information_cutoff", "2026-08-28T13:30:00+00:00"),
        ("research_binding", "b" * 64),
        ("request_sha256", "b" * 64),
    ],
)
def test_mixed_quarter_version_time_company_or_request_rejected(
    research, explanation_request, candidate, field, value
):
    candidate[field] = value
    with pytest.raises(ValueError):
        validate_candidate(research, explanation_request, candidate)


@pytest.mark.parametrize("location", ["candidate", "section", "claim", "citation"])
def test_scores_and_self_declared_approval_cannot_be_imported(
    research, explanation_request, candidate, location
):
    nodes = {
        "candidate": candidate,
        "section": candidate["sections"][0],
        "claim": candidate["sections"][0]["claims"][0],
        "citation": candidate["sections"][0]["claims"][0]["citations"][0],
    }
    nodes[location]["confidence"] = 0.99
    with pytest.raises(ValueError, match="額外欄位"):
        validate_candidate(research, explanation_request, candidate)


@pytest.mark.parametrize(
    "fault",
    [
        "missing_section",
        "duplicate_section",
        "missing_claim",
        "missing_citation",
        "wrong_quote",
        "unknown_block",
        "long_quote",
    ],
)
def test_incomplete_or_untraceable_explanations_fail_closed(
    research, explanation_request, candidate, fault
):
    claim = candidate["sections"][0]["claims"][0]
    if fault == "missing_section":
        candidate["sections"].pop()
    elif fault == "duplicate_section":
        candidate["sections"][1] = candidate["sections"][0]
    elif fault == "missing_claim":
        candidate["sections"][0]["claims"] = []
    elif fault == "missing_citation":
        claim["citations"] = []
    elif fault == "wrong_quote":
        claim["citations"][0]["quote"] = "Demand is guaranteed."
    elif fault == "unknown_block":
        claim["citations"][0]["paragraph_id"] = "unknown"
    elif fault == "long_quote":
        text = " ".join(["synthetic"] * 56)
        explanation_request["source_blocks"][0]["text"] = text
        candidate["request_sha256"] = canonical_sha(explanation_request)
        claim["citations"][0]["quote"] = text
    with pytest.raises(ValueError):
        validate_candidate(research, explanation_request, candidate)


def test_source_hash_substitution_and_duplicate_blocks_rejected(
    research, explanation_request, candidate
):
    for fault in ("hash", "duplicate"):
        changed = copy.deepcopy(explanation_request)
        if fault == "hash":
            changed["source_blocks"][0]["source_sha256"] = "b" * 64
        else:
            changed["source_blocks"] *= 2
        candidate["request_sha256"] = canonical_sha(changed)
        with pytest.raises(ValueError):
            validate_candidate(research, changed, candidate)


@pytest.mark.parametrize("fault", ["absent", "symlink", "oversized", "bad_json"])
def test_invalid_candidate_keeps_quant_and_exposes_no_raw_content(research, tmp_path, fault):
    path = tmp_path / "candidate.json"
    if fault == "symlink":
        actual = tmp_path / "actual.json"
        actual.write_text("{}")
        path.symlink_to(actual)
    elif fault == "oversized":
        path.write_text("x" * 2_000_001)
    elif fault == "bad_json":
        path.write_text("private model fragment - not JSON")
    original = copy.deepcopy(research)
    result = attach_synthesis(research, candidate_path=path)
    assert research == original
    assert result["current"] == research["current"]
    assert result["synthesis"]["ai"]["status"] == "blocked"
    assert result["synthesis"]["decision_ready"] is False
    assert "private model" not in json.dumps(result)


def test_candidate_read_only_view_rebuilds_request_and_never_invents_acceptance(
    research, explanation_request, candidate, monkeypatch, tmp_path
):
    from valuation_engine.research import ai_request

    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate))
    before = path.read_bytes()
    monkeypatch.setattr(ai_request, "build_request", lambda *args, **kwargs: explanation_request)
    result = attach_synthesis(research, candidate_path=path, raw_dir=tmp_path)
    assert result["synthesis"]["ai"]["status"] == "candidate_pending_review"
    assert result["synthesis"]["promotion_ready"] is False
    assert result["current"] == research["current"]
    assert path.read_bytes() == before


def test_deep_candidate_json_cannot_hide_quant_when_parser_exceeds_recursion(
    research, explanation_request, monkeypatch, tmp_path
):
    from valuation_engine.research import ai_request, synthesis

    path = tmp_path / "candidate.json"
    path.write_text("[]")
    monkeypatch.setattr(ai_request, "build_request", lambda *args, **kwargs: explanation_request)

    def too_deep(*args, **kwargs):
        raise RecursionError("synthetic parser depth limit")

    # Parser depth limits vary between supported Python versions. Force its
    # documented failure rather than depend on an interpreter-specific threshold.
    monkeypatch.setattr(synthesis.json, "loads", too_deep)
    original = copy.deepcopy(research)
    result = attach_synthesis(research, candidate_path=path, raw_dir=tmp_path)
    assert result["synthesis"]["ai"]["status"] == "blocked"
    assert result["current"] == research["current"]
    assert research == original
    assert path.read_text() == "[]"


@pytest.mark.parametrize("kind", [[], {}, ["fact"]])
def test_malformed_claim_kind_blocks_only_ai(
    research, explanation_request, candidate, monkeypatch, tmp_path, kind
):
    from valuation_engine.research import ai_request

    candidate["sections"][0]["claims"][0]["kind"] = kind
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(candidate))
    monkeypatch.setattr(ai_request, "build_request", lambda *args, **kwargs: explanation_request)
    result = attach_synthesis(research, candidate_path=path, raw_dir=tmp_path)
    assert result["synthesis"]["ai"]["status"] == "blocked"
    assert result["current"] == research["current"]


def test_workbench_load_attaches_candidate_without_rewriting_snapshot_or_pointer(
    research, explanation_request, candidate, monkeypatch, tmp_path
):
    from valuation_engine.research import ai_request
    from valuation_engine.research.workbench import Workbench

    monkeypatch.setattr(ai_request, "build_request", lambda *args, **kwargs: explanation_request)
    store = tmp_path / "workbench"
    store.mkdir()
    content = json.dumps(research).encode()
    identity = hashlib.sha256(content).hexdigest()
    snapshot = store / (identity + ".json")
    snapshot.write_bytes(content)
    pointer = store / "current.json"
    pointer.write_text(json.dumps({"snapshot_id": identity}))
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate))
    service = Workbench(
        tmp_path / "unused-formal.db", tmp_path / "raw", store, ai_candidate=candidate_path
    )
    protected = {path: path.read_bytes() for path in (snapshot, pointer, candidate_path)}
    result = service.load()
    assert result["snapshot_id"] == identity
    assert result["research"]["synthesis"]["ai"]["status"] == "candidate_pending_review"
    assert result["research"]["current"] == research["current"]
    assert "synthesis" not in json.loads(snapshot.read_bytes())
    assert {path: path.read_bytes() for path in protected} == protected
    assert sorted(path.name for path in store.iterdir()) == sorted([snapshot.name, pointer.name])
    assert not (tmp_path / "unused-formal.db").exists()


def test_product_load_attaches_candidate_without_writing_store_or_formal_source(
    research, explanation_request, candidate, monkeypatch, tmp_path
):
    from valuation_engine.research import ai_request
    from valuation_engine.research.product import Product
    from valuation_engine.research.product_store import digest

    monkeypatch.setattr(ai_request, "build_request", lambda *args, **kwargs: explanation_request)
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(candidate))
    service = Product(
        tmp_path / "unused-formal.db",
        tmp_path / "raw",
        tmp_path / "product",
        ai_candidate=candidate_path,
    )
    identity = service.store.publish("research", digest(research), research, 0, pointer="research")
    original = service.store.artifact(identity)
    protected = {path: path.read_bytes() for path in (service.store.path, candidate_path)}
    result = service.load()
    assert result["snapshot_id"] == identity
    assert result["research"]["synthesis"]["ai"]["status"] == "candidate_pending_review"
    assert result["research"]["current"] == research["current"]
    assert service.store.artifact(identity) == original
    assert "synthesis" not in original["payload"]
    assert {path: path.read_bytes() for path in protected} == protected
    assert [path.name for path in service.store.root.iterdir()] == ["operations.sqlite"]
    assert service.thread is None
    assert not (tmp_path / "unused-formal.db").exists()
