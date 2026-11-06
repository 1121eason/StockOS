from valuation_engine.ai.contracts import MAX_EVIDENCE_WORDS, PROMPT_VERSION
from valuation_engine.ai.prompts import TASKS


def test_prompt_v4_requires_exact_short_source_spans():
    task = TASKS["extract"]
    assert PROMPT_VERSION == "PromptSetV6-FSI"
    assert str(MAX_EVIDENCE_WORDS) in task
    assert "contiguous, verbatim substring" in task
    assert "do not paraphrase" in task
    assert "replace hyphen or dash characters" in task
    assert "under 400 characters" in task


def test_prompt_v4_distinguishes_mandatory_downside_from_adjustments():
    task = TASKS["challenge"]
    assert "kind=upside" in task
    assert "kind=downside" in task
    assert "kind=regime" in task
    assert "does not satisfy the downside challenge" in task
    assert "rather than fabricate" in task
    assert "free of digits" in task
    assert "fiscal-quarter labels" in task


def test_prompt_fsi_incorporation():
    from valuation_engine.ai.prompts import FSI_RUBRIC, ROLE_METHOD, SYSTEM

    assert "Curated FSI checks" in SYSTEM
    assert "MLPerf scores" in SYSTEM
    assert "Evidence roles are relative to each claim" in SYSTEM
    assert "Confidence is computed by the host" in SYSTEM
    assert "pricing_power" in FSI_RUBRIC
    assert "supply_constraint positive means supply relief" in ROLE_METHOD
