"""Offline result compatibility; no AGY process, global setting or real ledger."""

import copy
import json

import pytest

from valuation_engine.ai import agy_guarded
from valuation_engine.ai.agy_guarded import (
    GuardedTransport,
    PublicResponses,
    decode_result,
    strict_json,
)
from valuation_engine.ai.explanation_stages import challenge_schema, validate_challenge

SCHEMA = {
    "type": "object",
    "properties": {"answer": {"const": "unavailable"}},
    "required": ["answer"],
    "additionalProperties": False,
}
ANSWER = {"answer": "unavailable"}


def public_step(index, kind="agent_response", state="DONE", **changes):
    return {"conversation_id": "owned", "step_index": index, "step_type": kind,
            "state": state, **changes}


def test_complete_last_public_message_after_schema_correction_is_whole_json():
    messages = PublicResponses()
    messages.observe(public_step(1, text_delta="Earlier prose"))
    messages.observe(public_step(2, kind="user_input"))
    messages.observe(public_step(3, state="ACTIVE", text_delta='{"answer":'))
    messages.observe(public_step(3, text_delta='"unavailable"}'))
    value, meta = decode_result(envelope(response="Earlier prose plus answer"), SCHEMA,
                              final_public_response=messages.latest("owned"))
    assert value == ANSWER
    assert meta["source_field"] == "agent_response_stream_json"


@pytest.mark.parametrize("new_step", [
    public_step(2, kind="user_input"), public_step(2, state="ACTIVE", text_delta="{"),
    public_step(2),
])
def test_never_falls_back_to_earlier_complete_public_message(new_step):
    messages = PublicResponses()
    messages.observe(public_step(1, text_delta=json.dumps(ANSWER)))
    messages.observe(new_step)
    assert messages.latest("owned") is None


@pytest.mark.parametrize("bad", [
    public_step(2, conversation_id="foreign"),
    public_step(1, text_delta="duplicate"), public_step(2, text_delta={}),
])
def test_foreign_duplicate_or_wrong_typed_public_message_rejected(bad):
    messages = PublicResponses()
    messages.observe(public_step(1, text_delta="{}"))
    with pytest.raises(ValueError):
        messages.observe(bad)


@pytest.mark.parametrize("text", ['Answer: {"answer":"unavailable"}',
                                 '```json\n{"answer":"unavailable"}\n```',
                                 '{"answer":"unavailable","answer":"other"}'])
def test_whole_public_message_required_when_terminal_response_is_not_json(text):
    with pytest.raises(ValueError, match="RESULT_INVALID_JSON"):
        decode_result(envelope(response="display prose"), SCHEMA, final_public_response=text)


def test_primary_public_conflict_and_invalid_native_cannot_be_hidden():
    with pytest.raises(ValueError, match="CONFLICT"):
        decode_result(envelope(), SCHEMA, final_public_response='{"answer":"other"}')
    with pytest.raises(ValueError, match="NATIVE_OBJECT_INVALID"):
        decode_result(envelope(structured_output=None), SCHEMA,
                      final_public_response=json.dumps(ANSWER))


@pytest.fixture(autouse=True)
def no_live_process(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An offline compatibility test must not launch a process")

    monkeypatch.setattr(agy_guarded.subprocess, "Popen", forbidden)


def envelope(**changes):
    result = {
        "status": "SUCCESS",
        "json_schema": copy.deepcopy(SCHEMA),
        "response": json.dumps(ANSWER),
    }
    result.update(changes)
    return result


@pytest.mark.parametrize("native", [False, True])
def test_native_and_response_object_paths_preserve_stage_validation_requirement(native):
    result = envelope()
    if native:
        result["structured_output"] = copy.deepcopy(ANSWER)
    before = copy.deepcopy(result)
    output, metadata = decode_result(result, SCHEMA)
    assert output == ANSWER
    assert result == before
    assert metadata["source_field"] == ("structured_output" if native else "response_json")
    assert metadata["native_structured_output_present"] is native
    assert metadata["schema_echo_matches_request"] is True
    assert metadata["stage_validation"] == "REQUIRED_BEFORE_ADMISSION"
    assert "unavailable" not in json.dumps(metadata)
    output["answer"] = "mutated copy"
    assert result == before


def test_response_allows_only_json_whitespace_and_preserves_unicode():
    response = ' \n {"answer":"unavailable","note":"合成測試"} \t'
    output, _ = decode_result(envelope(response=response), SCHEMA)
    assert output["note"] == "合成測試"
    # Object decoding is deliberately separate from the required stage gate.
    assert set(output) == {"answer", "note"}


@pytest.mark.parametrize("value", [None, False, 0, [], "{}"])
def test_invalid_native_object_cannot_fall_back_to_valid_response(value):
    with pytest.raises(ValueError, match="RESULT_NATIVE_OBJECT_INVALID"):
        decode_result(envelope(structured_output=value), SCHEMA)


@pytest.mark.parametrize("value", [None, False, 0, [], {}])
def test_response_must_be_documented_string_type(value):
    with pytest.raises(ValueError, match="RESULT_RESPONSE_STRING_REQUIRED"):
        decode_result(envelope(response=value), SCHEMA)


@pytest.mark.parametrize(
    "response",
    [
        '```json\n{"answer":"unavailable"}\n```',
        'Answer: {"answer":"unavailable"}',
        '{"answer":"unavailable"} trailing text',
        '{"answer":"unavailable"}{"answer":"unavailable"}',
        '{"answer":"unavailable","answer":"available"}',
        '{"nested":{"x":1,"x":2}}',
        '{"n":NaN}',
        '{"n":Infinity}',
        '{"n":-Infinity}',
        '{"n":1e999}',
        '{"answer":',
    ],
)
def test_no_json_extraction_duplicate_keys_or_nonfinite_values(response):
    with pytest.raises(ValueError, match="RESULT_INVALID_JSON"):
        decode_result(envelope(response=response), SCHEMA)


@pytest.mark.parametrize("response", ["[]", "null", "true", "1", '"object text"'])
def test_complete_json_still_requires_top_level_object(response):
    with pytest.raises(ValueError, match="RESULT_OBJECT_REQUIRED"):
        decode_result(envelope(response=response), SCHEMA)


@pytest.mark.parametrize("schema", [None, False, [], {"type": "array"}])
def test_missing_changed_or_malformed_echo_is_not_accepted(schema):
    with pytest.raises(ValueError, match="RESULT_SCHEMA_BINDING_MISMATCH"):
        decode_result(envelope(json_schema=schema), SCHEMA)
    result = envelope()
    del result["json_schema"]
    with pytest.raises(ValueError, match="RESULT_SCHEMA_BINDING_MISMATCH"):
        decode_result(result, SCHEMA)


@pytest.mark.parametrize("schema", [None, [], False, {"type": "array"}])
def test_expected_contract_must_be_an_object_schema(schema):
    with pytest.raises(ValueError, match="RESULT_OBJECT_SCHEMA_REQUIRED"):
        decode_result(envelope(), schema)


@pytest.mark.parametrize("status", [None, "ERROR", "CANCELLED", "UNKNOWN"])
def test_provider_failure_cannot_become_successful_object(status):
    with pytest.raises(ValueError, match="PROVIDER_OR_SCHEMA_FAILURE"):
        decode_result(envelope(status=status), SCHEMA)


@pytest.mark.parametrize("error", ["failure", False, 0, [], {}])
def test_success_with_contradictory_error_is_rejected(error):
    with pytest.raises(ValueError, match="RESULT_CONTRADICTORY_ERROR"):
        decode_result(envelope(error=error), SCHEMA)


def test_native_and_text_conflict_is_rejected_instead_of_choosing_one():
    with pytest.raises(ValueError, match="RESULT_OUTPUT_CONFLICT"):
        decode_result(envelope(structured_output={"answer": "different"}), SCHEMA)


def test_duplicate_envelope_status_cannot_be_silently_overwritten():
    with pytest.raises(ValueError, match="RESULT_INVALID_JSON"):
        strict_json('{"result":{"status":"ERROR","status":"SUCCESS"}}')


@pytest.mark.parametrize("bad_field", [None, "promotion_ready", "human_review_required", "extra"])
def test_real_stage_validator_still_controls_admission_and_budget(tmp_path, monkeypatch, bad_field):
    cli = tmp_path / "synthetic-cli"
    cli.write_bytes(b"not executable")
    monkeypatch.setattr(agy_guarded, "CLI", cli)
    monkeypatch.setattr(agy_guarded, "CLI_SHA", agy_guarded.sha(cli.read_bytes()))
    request = {
        "version": "StockOSAIExplanationRequestV1",
        "sources": [{"id": 1, "sha256": "a" * 64}],
        "source_blocks": [
            {"paragraph_id": "p1", "source_id": 1, "source_sha256": "a" * 64, "text": "Synthetic."}
        ],
    }
    answer = {
        "summary": "合成測試，仍需人工審查。",
        "issues": [],
        "unassessed_topics": [],
        "human_review_required": True,
        "promotion_ready": False,
    }
    if bad_field == "promotion_ready":
        answer[bad_field] = True
    elif bad_field == "human_review_required":
        answer[bad_field] = 1
    elif bad_field == "extra":
        answer[bad_field] = "unapproved field"
    schema = challenge_schema()

    class Budget:
        def __init__(self):
            self.outcomes = []

        def reserve(self, phase, **kwargs):
            return "synthetic-attempt"

        def finish(self, attempt, status, **kwargs):
            self.outcomes.append(status)

    budget = Budget()
    transport = GuardedTransport(
        output=tmp_path,
        budget=budget,
        policy_hash="synthetic",
        protected_hashes={},
        denied_roots=[],
    )

    def fixture_call(*args, **kwargs):
        output, metadata = decode_result(
            {"status": "SUCCESS", "json_schema": schema, "response": json.dumps(answer)}, schema
        )
        return {
            "status": "PASS",
            "denied_tools": [],
            "structured_output": output,
            "response_decoding": metadata,
        }

    monkeypatch.setattr(transport, "_call", fixture_call)
    call = lambda: transport.request(  # noqa: E731
        "synthetic-challenge",
        {},
        diagnostic=True,
        validate=lambda value: validate_challenge(request, value),
    )
    admitted_path = tmp_path / "synthetic-attempt/admitted.json"
    if bad_field is None:
        output, receipt = call()
        assert output == answer
        assert receipt["response_decoding"]["stage_validation"] == "PASS"
        assert admitted_path.exists()
        assert budget.outcomes == ["COMPLETED"]
    else:
        with pytest.raises(ValueError):
            call()
        assert not admitted_path.exists()
        assert budget.outcomes == ["FAILED"]
        failed = json.loads((tmp_path / "synthetic-attempt/result.json").read_text())
        assert failed["structured_output"] is None
        assert failed["response_decoding"]["stage_validation"] == "REQUIRED_BEFORE_ADMISSION"
