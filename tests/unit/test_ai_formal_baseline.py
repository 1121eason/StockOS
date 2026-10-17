"""Keep experimental FSI policy changes outside the approved cbb78db formal baseline."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from valuation_engine.ai import contracts, prompts, service, validation
from valuation_engine.db.schema import AIAnalysisRun, AIAnalystSnapshot, AIHumanReview
from valuation_engine.db.store import company


@pytest.mark.parametrize(
    "module,expected_hash",
    [
        (contracts, "3327435670f96f63ba6b13fdce3979cbba17701396a74359ad1c2399468f9301"),
        (prompts, "fc0e72bf5ffb59c2566447533e83cbfb2da149b0b1328c2d80162a936c8e7c09"),
        (service, "248a73bd93aeb856e837a8d28c413319193c9de56a0edb42c44d657cb342665d"),
        (validation, "de8510f223aab797700d5f40bad43d8544ded02b6ae219b3c8f2e933d05a2996"),
    ],
)
def test_formal_modules_match_approved_cbb78db_bytes(module, expected_hash):
    assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == expected_hash


def test_formal_versions_and_prompt_payload_remain_canonical():
    assert contracts.POLICY_VERSION == "AIAnalystPolicyV1"
    assert contracts.PROMPT_VERSION == "PromptSetV1"
    assert contracts.SCHEMA_VERSION == "FeatureSchemaV1"
    assert "speaker_status" not in contracts.EvidenceDraft.model_fields
    assert "speaker_role" not in contracts.EvidenceDraft.model_fields
    assert "max 55 words" in prompts.TASKS["extract"]
    payload = {"evidence": []}
    exact = prompts.prompt("synthesize", payload, contracts.Synthesis)
    assert exact["untrusted_data"] is payload
    assert exact["prompt_version"] == "PromptSetV1"
    assert exact["schema_version"] == "FeatureSchemaV1"
    assert "feature_evidence_keys" not in exact["untrusted_data"]
    assert "Curated FSI checks" not in exact["system"]


def test_prepare_uses_canonical_context_without_missing_package_dependency(monkeypatch):
    db = object()
    cutoff = datetime(2020, 1, 1, tzinfo=UTC)
    quant_run = SimpleNamespace(company_id=1, information_cutoff=cutoff)
    context = {"quarter": "synthetic-quarter"}
    sources = {"documents": [], "blocks": []}
    calls = []

    def context_for(actual_db, actual_run):
        assert (actual_db, actual_run) == (db, quant_run)
        return context

    def retrieve(*args):
        calls.append(args)
        return sources

    monkeypatch.setattr(service, "context_for", context_for)
    monkeypatch.setattr(service, "retrieve", retrieve)

    prepared = service.prepare(db, quant_run, "synthetic-raw-dir")

    assert prepared == {"quant_context": context, "sources": sources}
    assert prepared["quant_context"] is context
    assert prepared["sources"] is sources
    assert calls == [(db, 1, cutoff, "synthetic-raw-dir")]


def add_snapshot(db, quarter, provider, *, prompt_version="PromptSetV1", reviewed=False):
    at = datetime(2020, 1, 1, tzinfo=UTC)
    run = AIAnalysisRun(
        company_id=company(db).id,
        quarter=quarter,
        as_of_timestamp=at,
        information_cutoff=at,
        source_document_ids=[],
        model_provider=provider,
        model_name="synthetic-model",
        model_version="synthetic-version",
        prompt_version=prompt_version,
        schema_version="FeatureSchemaV1",
        policy_version="AIAnalystPolicyV1",
        request_hash=f"synthetic-{quarter}-{provider}-{prompt_version}",
        context_json={},
        settings_json={},
    )
    db.add(run)
    db.flush()
    snapshot = AIAnalystSnapshot(
        company_id=run.company_id,
        as_of_timestamp=at,
        analysis_run_id=run.id,
        overall_qualitative_confidence=0,
        prompt_version=prompt_version,
        model_version="synthetic-version",
        metadata_json={"synthetic_test_only": True},
    )
    db.add(snapshot)
    if reviewed:
        for category in validation.CATEGORIES:
            db.add(
                AIHumanReview(
                    analysis_run_id=run.id,
                    category=category,
                    verdict="correct",
                    reviewer="Synthetic fixture reviewer",
                    notes="Synthetic test only; not an actual human review.",
                    evidence_ids=[],
                )
            )
    db.flush()
    return snapshot


def test_requested_claude_review_cannot_fall_back_to_completed_codex_reviews(db):
    for quarter in validation.QUARTERS[:5]:
        add_snapshot(db, quarter, "codex_cli", reviewed=True)

    codex = validation.review_status(db, provider="codex_cli")
    claude = validation.review_status(db, provider="claude_cli")

    assert codex["completed"] == 35
    assert codex["human_gate_complete"] is True
    assert claude["completed"] == 0
    assert claude["human_gate_complete"] is False
    assert len(claude["pending"]) == 35
    assert validation.completed(db, validation.QUARTERS[0], "claude_cli") is None


def test_completed_preserves_provider_model_and_canonical_snapshot_order(db):
    quarter = validation.QUARTERS[0]
    first = add_snapshot(db, quarter, "claude_cli")
    add_snapshot(db, quarter, "claude_cli", prompt_version="PromptSetV6", reviewed=True)
    add_snapshot(db, quarter, "codex_cli", reviewed=True)

    assert validation.completed(db, quarter, "claude_cli").id == first.id
    assert validation.completed(db, quarter, "claude_cli", "synthetic-model").id == first.id
    assert validation.completed(db, quarter, "claude_cli", "other-model") is None
