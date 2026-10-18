"""Synthetic schema-2 policy provenance and immutable schema-1 compatibility contracts.

No private policy exports, original databases, or real quarterly inputs are used here.
The legacy fingerprint was captured from schema-1 before the format extension.
"""

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from valuation_engine.research import workspace

LEGACY_FINGERPRINT = "bd0a2402b5bbefb85f12b989b7b75f0a4284c1878be584a982a09a7e0d691425"
LEGACY_INPUT_HASH = "366eb0d71446ade3cbb1e465efe5fdc4382b62b6d171c0e1abd42cb825e4df0d"
VINTAGE_FLAGS = (
    "historical_oos",
    "source_vintages_verified",
    "model_vintages_verified",
    "price_vintages_verified",
)


def canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rehash(source: dict) -> None:
    source["content_sha256"] = digest(canonical(source["content"]))
    source["assumption_content_hash"] = digest(
        json.dumps(source["content"], sort_keys=True, ensure_ascii=True, allow_nan=False)
    )


def legacy_bundle() -> dict:
    def item(value: str) -> dict:
        return {
            "value": value,
            "source_ids": ["issuer_2024"],
            "available_at": "2024-06-01T00:00:00Z",
        }

    return {
        "schema_version": 1,
        "ticker": "DEMO",
        "name": "Synthetic Company",
        "as_of": "2024-06-02T00:00:00Z",
        "data_kind": "synthetic",
        "sources": [
            {
                "id": "issuer_2024",
                "url": "https://example.com/filing",
                "published_at": "2024-06-01T00:00:00Z",
                "retrieved_at": "2025-01-01T00:00:00Z",
                "sha256": "a" * 64,
            }
        ],
        "inputs": {
            "cash": item("100"),
            "debt": item("200"),
            "shares": item("100"),
            "wacc": item("0.10"),
            "terminal_growth": item("0.02"),
            "forecast_cashflows": [item(str(v)) for v in (100, 110, 120, 130, 140)],
        },
        "assumptions": {
            "classification": workspace.CLASSIFICATION,
            "rationale": "Reconstructed annual FCFF assumptions in absolute USD.",
        },
    }


def policy_source() -> dict:
    source = {
        "kind": "internal_policy_artifact",
        "id": "internal_policy",
        "source_type": "fixed_research_policy_not_return_fitted",
        "policy_version": "SyntheticPolicyV1",
        "assumption_set_id": 1,
        "content_sha256": "",
        "assumption_content_hash": "",
        "content": {
            "version": "SyntheticPolicyV1",
            "classification": "research_reconstructed_internal",
            "effective_from": "2026-01-01T00:00:00Z",
            "wacc_base": "0.10",
            "terminal_growth_base": "0.02",
        },
        "created_at": "2026-01-02T00:00:00Z",
        "effective_from": "2026-01-01T00:00:00Z",
        "observed_at": "2026-01-03T00:00:00Z",
        "published_at": None,
        "historical_available_at": None,
        "source_reference": "Synthetic internal policy fixture; no public publication claimed",
        "parameter_records": [
            {
                "record_id": 11,
                "parameter": "wacc",
                "value": "0.10",
                "created_at": "2026-01-02T00:00:01Z",
            },
            {
                "record_id": 12,
                "parameter": "terminal_growth",
                "value": "0.02",
                "created_at": "2026-01-02T00:00:02Z",
            },
        ],
    }
    rehash(source)
    return source


def policy_bundle() -> dict:
    bundle = legacy_bundle()
    bundle.update(schema_version=2, economic_as_of=bundle["as_of"], as_of="2026-01-04T00:00:00Z")
    bundle["sources"][0]["kind"] = "external_document"
    bundle["sources"].append(policy_source())
    for name in ("wacc", "terminal_growth"):
        bundle["inputs"][name].update(
            source_ids=["internal_policy"], available_at="2026-01-03T00:00:00Z"
        )
    return bundle


def policy(bundle: dict) -> dict:
    return bundle["sources"][1]


def assert_rejected(tmp_path: Path, bundle: dict) -> None:
    database = tmp_path / "rejected.sqlite"
    with pytest.raises(ValueError):
        workspace.import_bundle(database, bundle)
    assert not database.exists(), "Invalid provenance must fail before database creation"


def store_snapshot(database: Path) -> tuple:
    with sqlite3.connect(database) as connection:
        return (
            connection.execute("PRAGMA user_version").fetchone(),
            connection.execute("PRAGMA application_id").fetchone(),
            connection.execute("SELECT * FROM workspace_meta").fetchall(),
            connection.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall(),
        )


def stored_row(database: Path, run_id: str) -> tuple:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            "SELECT * FROM research_runs WHERE run_id=?", (run_id,)
        ).fetchone()


@pytest.fixture
def frozen_clock(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 2, 1, tzinfo=UTC)
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(workspace, "datetime", FrozenDatetime)


def test_schema_one_full_result_remains_byte_identical(tmp_path, frozen_clock):
    result = workspace.import_bundle(tmp_path / "legacy.sqlite", legacy_bundle())
    assert digest(canonical(result)) == LEGACY_FINGERPRINT
    assert result["input_hash"] == LEGACY_INPUT_HASH
    assert result["run_id"] == "rw1_" + LEGACY_INPUT_HASH
    for key in (*VINTAGE_FLAGS, "economic_as_of", "provenance_limitations"):
        assert key not in result
    assert stored_row(tmp_path / "legacy.sqlite", result["run_id"])[3:] == (
        canonical(result),
        LEGACY_FINGERPRINT,
    )


def test_internal_policy_preserves_null_publication_and_canonical_dcf(tmp_path):
    bundle = policy_bundle()
    result = workspace.import_bundle(tmp_path / "research.sqlite", bundle)
    baseline = workspace.import_bundle(tmp_path / "baseline.sqlite", legacy_bundle())
    assert result["bundle"] == bundle
    assert result["valuation"] == baseline["valuation"]
    assert result["schema_version"] == 2
    assert result["run_id"] == "rw1_" + digest(canonical(bundle))
    assert result["run_id"] != baseline["run_id"]
    assert result["mode"] == "research"
    assert result["classification"] == workspace.CLASSIFICATION
    assert result["formal_decision"] == "withheld"
    assert result["source_verification"] == "asserted_unverified"
    assert result["economic_as_of"] == bundle["economic_as_of"]
    assert result["as_of"] == bundle["as_of"]
    for key in VINTAGE_FLAGS:
        assert result[key] is False
    assert isinstance(result["provenance_limitations"], list) and result["provenance_limitations"]
    assert all(isinstance(value, str) and value for value in result["provenance_limitations"])
    loaded = workspace.load_run(tmp_path / "research.sqlite", result["run_id"])
    for field in ("published_at", "historical_available_at"):
        assert field in policy(loaded["bundle"])
        assert policy(loaded["bundle"])[field] is None
    assert "url" not in policy(loaded["bundle"])
    assert "retrieved_at" not in policy(loaded["bundle"])


def test_mixed_store_retains_schema_identity_legacy_bytes_and_immutable_replay(
    tmp_path, frozen_clock
):
    database = tmp_path / "mixed.sqlite"
    old = workspace.import_bundle(database, legacy_bundle())
    before_row = stored_row(database, old["run_id"])
    before_schema = store_snapshot(database)
    assert before_schema[:3] == (
        (1,),
        (0x53525731,),
        [(1, "stockos-isolated-research-workspace-v1")],
    )
    new = workspace.import_bundle(database, policy_bundle())
    assert store_snapshot(database) == before_schema
    assert stored_row(database, old["run_id"]) == before_row
    assert digest(before_row[3]) == LEGACY_FINGERPRINT
    assert workspace.import_bundle(database, legacy_bundle()) == old
    assert workspace.import_bundle(database, policy_bundle()) == new
    assert {item["run_id"] for item in workspace.list_runs(database)} == {
        old["run_id"],
        new["run_id"],
    }
    assert workspace.load_run(database, old["run_id"]) == old
    assert workspace.load_run(database, new["run_id"]) == new
    with sqlite3.connect(database) as connection:
        for statement in (
            "DELETE FROM research_runs",
            "UPDATE research_runs SET result_hash='forged'",
            "INSERT OR REPLACE INTO research_runs SELECT * FROM research_runs",
            "DELETE FROM workspace_meta",
            "UPDATE workspace_meta SET identity='forged'",
            "INSERT OR REPLACE INTO workspace_meta SELECT * FROM workspace_meta",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(statement)
    assert stored_row(database, old["run_id"]) == before_row


def test_schema_two_concurrent_mixed_replay_is_idempotent(tmp_path):
    database = tmp_path / "concurrent.sqlite"
    first = workspace.import_bundle(database, legacy_bundle())
    second = workspace.import_bundle(database, policy_bundle())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda i: workspace.import_bundle(
                    database, policy_bundle() if i % 2 else legacy_bundle()
                ),
                range(16),
            )
        )
    assert all(result == (second if i % 2 else first) for i, result in enumerate(results))
    assert len(workspace.list_runs(database)) == 2


def test_reordered_objects_replay_without_aliasing_and_different_content_has_new_identity(tmp_path):
    database = tmp_path / "research.sqlite"
    bundle = policy_bundle()
    original = workspace.import_bundle(database, bundle)
    source = policy(bundle)
    source["content"] = dict(reversed(list(source["content"].items())))
    rehash(source)
    assert workspace.import_bundle(database, dict(reversed(list(bundle.items())))) == original
    source["content"]["synthetic_note"] = "A retained source payload field"
    rehash(source)
    newer = workspace.import_bundle(database, bundle)
    assert newer["run_id"] != original["run_id"]
    assert newer["valuation"] == original["valuation"]
    bundle["sources"].clear()
    policy(newer["bundle"])["content"]["wacc_base"] = "999"
    newer["provenance_limitations"].clear()
    reread = workspace.load_run(database, newer["run_id"])
    assert policy(reread["bundle"])["content"]["wacc_base"] == "0.10"
    assert reread["provenance_limitations"] == original["provenance_limitations"]


def test_both_hashes_are_independently_recomputed_using_correct_json_conventions(tmp_path):
    bundle = policy_bundle()
    source = policy(bundle)
    source["content"]["nested_payload"] = {
        "unicode": "\u03c0",
        "ordered": [1, {"b": True, "a": None}],
    }
    rehash(source)
    assert source["content_sha256"] != source["assumption_content_hash"]
    result = workspace.import_bundle(tmp_path / "research.sqlite", bundle)
    assert policy(result["bundle"])["content"] == source["content"]
    assert policy(result["bundle"])["content_sha256"] == digest(canonical(source["content"]))
    assert policy(result["bundle"])["assumption_content_hash"] == digest(
        json.dumps(source["content"], sort_keys=True, ensure_ascii=True, allow_nan=False)
    )


@pytest.mark.parametrize("field", ["content_sha256", "assumption_content_hash"])
@pytest.mark.parametrize("bad", ["0" * 64, "A" * 64, "bad", None, True, 1])
def test_each_hash_is_strict_and_recomputed(tmp_path, field, bad):
    bundle = policy_bundle()
    policy(bundle)[field] = bad
    assert_rejected(tmp_path, bundle)


def test_compact_hash_cannot_replace_original_assumption_identity(tmp_path):
    bundle = policy_bundle()
    policy(bundle)["assumption_content_hash"] = policy(bundle)["content_sha256"]
    assert_rejected(tmp_path, bundle)


def test_default_separator_hash_cannot_replace_compact_content_identity(tmp_path):
    bundle = policy_bundle()
    policy(bundle)["content_sha256"] = policy(bundle)["assumption_content_hash"]
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("field", ["content_sha256", "assumption_content_hash", "neither"])
def test_payload_mutation_requires_both_hashes_to_be_updated(tmp_path, field):
    bundle = policy_bundle()
    source = policy(bundle)
    original = copy.deepcopy(source)
    source["content"]["extra_policy_metadata"] = "Synthetic only"
    rehash(source)
    if field == "neither":
        source["content_sha256"] = original["content_sha256"]
        source["assumption_content_hash"] = original["assumption_content_hash"]
    else:
        source[field] = original[field]
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("characters,accepted", [(65535, True), (65536, True), (65537, False)])
def test_canonical_policy_content_character_limit(tmp_path, characters, accepted):
    bundle = policy_bundle()
    source = policy(bundle)
    source["content"]["padding"] = ""
    source["content"]["padding"] = "x" * (characters - len(canonical(source["content"])))
    rehash(source)
    assert len(canonical(source["content"])) == characters
    if accepted:
        result = workspace.import_bundle(tmp_path / "bounded.sqlite", bundle)
        assert policy(result["bundle"])["content"] == source["content"]
    else:
        assert_rejected(tmp_path, bundle)


def test_content_limit_counts_ascii_escaped_canonical_characters(tmp_path):
    bundle = policy_bundle()
    source = policy(bundle)
    source["content"]["unicode_padding"] = "\u03c0" * 11000
    rehash(source)
    assert len(json.dumps(source["content"], ensure_ascii=False)) < 65536
    assert len(canonical(source["content"])) > 65536
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("bad", [None, [], "policy", 1, True])
def test_policy_content_must_be_an_object(tmp_path, bad):
    bundle = policy_bundle()
    policy(bundle)["content"] = bad
    rehash(policy(bundle))
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), {1, 2}])
def test_non_json_and_nonfinite_retained_content_is_rejected(tmp_path, bad):
    bundle = policy_bundle()
    policy(bundle)["content"]["extra"] = bad
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("field", list(policy_source()))
def test_every_internal_source_field_is_required(tmp_path, field):
    bundle = policy_bundle()
    del policy(bundle)[field]
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize(
    "field", ["version", "classification", "effective_from", "wacc_base", "terminal_growth_base"]
)
def test_required_policy_content_fields_cannot_be_omitted(tmp_path, field):
    bundle = policy_bundle()
    del policy(bundle)["content"][field]
    rehash(policy(bundle))
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("field", ["record_id", "parameter", "value", "created_at"])
def test_every_parameter_record_field_is_required(tmp_path, field):
    bundle = policy_bundle()
    del policy(bundle)["parameter_records"][0][field]
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("target", ["bundle", "source", "record", "assumptions", "input"])
@pytest.mark.parametrize("field", ["historical_oos", "source_vintages_verified", "formal_approved"])
def test_extra_claim_fields_cannot_promote_internal_policy(tmp_path, target, field):
    bundle = policy_bundle()
    targets = {
        "bundle": bundle,
        "source": policy(bundle),
        "record": policy(bundle)["parameter_records"][0],
        "assumptions": bundle["assumptions"],
        "input": bundle["inputs"]["wacc"],
    }
    targets[target][field] = True
    assert_rejected(tmp_path, bundle)


def test_retained_content_claims_never_promote_fixed_result_guards(tmp_path):
    bundle = policy_bundle()
    policy(bundle)["content"].update({key: True for key in VINTAGE_FLAGS})
    policy(bundle)["content"].update(formal_decision="buy", source_verification="verified")
    rehash(policy(bundle))
    result = workspace.import_bundle(tmp_path / "research.sqlite", bundle)
    assert all(result[key] is False for key in VINTAGE_FLAGS)
    assert result["formal_decision"] == "withheld"
    assert result["source_verification"] == "asserted_unverified"


@pytest.mark.parametrize(
    "field,bad",
    [
        ("kind", "policy"),
        ("kind", None),
        ("id", "bad/id"),
        ("id", True),
        ("id", ""),
        ("id", "x" * 65),
        ("source_type", "return_fitted"),
        ("source_type", None),
        ("policy_version", ""),
        ("policy_version", None),
        ("policy_version", "DifferentPolicyV1"),
        ("source_reference", ""),
        ("source_reference", None),
        ("source_reference", True),
        ("source_reference", "bad\u0000reference"),
    ],
)
def test_malformed_source_identity_and_text_rejected(tmp_path, field, bad):
    bundle = policy_bundle()
    policy(bundle)[field] = bad
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("bad", [True, False, 0, -1, "1", 1.0, None, [], {}])
@pytest.mark.parametrize("field", ["assumption_set_id", "record_id"])
def test_database_record_identifiers_are_positive_integers_not_booleans(tmp_path, field, bad):
    bundle = policy_bundle()
    target = (
        policy(bundle) if field == "assumption_set_id" else policy(bundle)["parameter_records"][0]
    )
    target[field] = bad
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.update(parameter_records=[]),
        lambda s: s.update(parameter_records=None),
        lambda s: s.update(parameter_records={}),
        lambda s: s["parameter_records"].pop(),
        lambda s: s["parameter_records"].append(copy.deepcopy(s["parameter_records"][0])),
        lambda s: s["parameter_records"][1].update(record_id=11),
        lambda s: s["parameter_records"][1].update(parameter="wacc"),
        lambda s: s["parameter_records"][0].update(parameter="cash"),
        lambda s: s["parameter_records"][0].update(parameter=True),
        lambda s: s["parameter_records"][0].update(extra="ignored"),
    ],
)
def test_parameter_records_are_exact_unique_and_rate_only(tmp_path, change):
    bundle = policy_bundle()
    change(policy(bundle))
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("field", ["published_at", "historical_available_at"])
@pytest.mark.parametrize("bad", ["2022-01-01T00:00:00Z", "2026-01-03T00:00:00Z", "", 0, False, {}])
def test_internal_publication_and_historical_availability_must_be_literal_null(
    tmp_path, field, bad
):
    bundle = policy_bundle()
    policy(bundle)[field] = bad
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize(
    "field",
    ["created_at", "effective_from", "observed_at", "parameter_created_at", "economic_as_of"],
)
@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        "2026-01-01",
        "2026-01-01T00:00:00",
        "2026-13-01T00:00:00Z",
        "2026-01-01T25:00:00Z",
        "2026-01-01T00:00:00+25:00",
    ],
)
def test_policy_timestamps_require_valid_timezone_aware_iso_dates(tmp_path, field, bad):
    bundle = policy_bundle()
    if field == "economic_as_of":
        bundle[field] = bad
    elif field == "parameter_created_at":
        policy(bundle)["parameter_records"][0]["created_at"] = bad
    else:
        policy(bundle)[field] = bad
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize(
    "field,value",
    [
        ("created_at", "2026-01-03T00:00:01Z"),
        ("effective_from", "2026-01-03T00:00:01Z"),
        ("observed_at", "2026-01-04T00:00:01Z"),
        ("parameter_created_at", "2026-01-01T23:59:59Z"),
        ("parameter_created_at", "2026-01-03T00:00:01Z"),
        ("economic_as_of", "2026-01-04T00:00:01Z"),
        ("available_at", "2026-01-02T23:59:59Z"),
        ("available_at", "2026-01-04T00:00:01Z"),
    ],
)
def test_policy_temporal_order_is_fail_closed(tmp_path, field, value):
    bundle = policy_bundle()
    source = policy(bundle)
    if field == "economic_as_of":
        bundle[field] = value
    elif field == "available_at":
        bundle["inputs"]["wacc"][field] = value
    elif field == "parameter_created_at":
        source["parameter_records"][0]["created_at"] = value
    else:
        source[field] = value
        if field == "effective_from":
            source["content"][field] = value
            rehash(source)
    assert_rejected(tmp_path, bundle)


def test_equal_time_boundaries_and_equivalent_offsets_are_allowed(tmp_path):
    bundle = policy_bundle()
    source = policy(bundle)
    bundle["economic_as_of"] = bundle["as_of"] = "2026-01-03T00:00:00Z"
    source["created_at"] = "2026-01-02T19:00:00-05:00"
    source["effective_from"] = "2026-01-03T01:00:00+01:00"
    source["content"]["effective_from"] = source["effective_from"]
    for record in source["parameter_records"]:
        record["created_at"] = "2026-01-03T00:00:00Z"
    rehash(source)
    result = workspace.import_bundle(tmp_path / "research.sqlite", bundle)
    assert result["bundle"] == bundle
    assert result["historical_oos"] is False


@pytest.mark.parametrize("year", [2022, 2023, 2024, 2025])
def test_current_artifact_cannot_be_imported_under_historical_reconstruction_cutoff(tmp_path, year):
    bundle = policy_bundle()
    cutoff = f"{year}-12-31T23:59:59Z"
    bundle["as_of"] = bundle["economic_as_of"] = cutoff
    # Isolate the policy boundary: all external evidence satisfies each older cutoff.
    bundle["sources"][0]["published_at"] = "2022-01-01T00:00:00Z"
    for item in [bundle["inputs"][name] for name in ("cash", "debt", "shares")]:
        item["available_at"] = "2022-01-01T00:00:00Z"
    for item in bundle["inputs"]["forecast_cashflows"]:
        item["available_at"] = "2022-01-01T00:00:00Z"
    for name in ("wacc", "terminal_growth"):
        bundle["inputs"][name]["available_at"] = cutoff
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("field", ["cash", "debt", "shares", *range(5)])
@pytest.mark.parametrize("value", [None, "100"])
@pytest.mark.parametrize("available", [None, "2026-01-03T00:00:00Z"])
def test_internal_policy_never_cites_financial_inputs_even_when_null(
    tmp_path, field, value, available
):
    bundle = policy_bundle()
    item = (
        bundle["inputs"]["forecast_cashflows"][field]
        if isinstance(field, int)
        else bundle["inputs"][field]
    )
    item.update(value=value, source_ids=["internal_policy"], available_at=available)
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("field", ["cash", "debt", "shares", *range(5)])
def test_null_financial_input_cannot_hide_internal_policy_among_external_citations(tmp_path, field):
    bundle = policy_bundle()
    item = (
        bundle["inputs"]["forecast_cashflows"][field]
        if isinstance(field, int)
        else bundle["inputs"][field]
    )
    item.update(value=None, source_ids=["issuer_2024", "internal_policy"], available_at=None)
    assert_rejected(tmp_path, bundle)


def test_null_financial_inputs_without_internal_citations_still_mean_unavailable(tmp_path):
    bundle = policy_bundle()
    for name in ("cash", "debt", "shares"):
        bundle["inputs"][name].update(value=None, source_ids=[], available_at=None)
    for item in bundle["inputs"]["forecast_cashflows"]:
        item.update(value=None, source_ids=[], available_at=None)
    result = workspace.import_bundle(tmp_path / "research.sqlite", bundle)
    assert result["valuation"]["status"] == "unavailable"
    assert result["valuation"]["reason"] == "missing_required_inputs"
    assert "per_share" not in result["valuation"]
    assert all(row["status"] == "unavailable" for row in result["valuation"]["scenarios"])
    assert result["formal_decision"] == "withheld"


@pytest.mark.parametrize("name", ["wacc", "terminal_growth"])
@pytest.mark.parametrize(
    "ids", [["internal_policy", "issuer_2024"], ["internal_policy", "internal_policy"], []]
)
def test_internal_rate_cites_exactly_one_internal_artifact(tmp_path, name, ids):
    bundle = policy_bundle()
    bundle["inputs"][name]["source_ids"] = ids
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("name", ["wacc", "terminal_growth"])
@pytest.mark.parametrize("value", [None, "0.11", "0.0200000000000000000001", True, "NaN"])
def test_rate_input_is_non_null_finite_and_matches_its_exact_parameter(tmp_path, name, value):
    bundle = policy_bundle()
    bundle["inputs"][name]["value"] = value
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("target", ["record", "content"])
@pytest.mark.parametrize("value", [None, "0.11", True, "NaN"])
def test_record_and_content_rates_must_agree_even_with_fresh_hashes(tmp_path, index, target, value):
    bundle = policy_bundle()
    source = policy(bundle)
    if target == "record":
        source["parameter_records"][index]["value"] = value
    else:
        source["content"][("wacc_base", "terminal_growth_base")[index]] = value
    rehash(source)
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "OtherPolicy"),
        ("classification", "historical_oos"),
        ("classification", workspace.CLASSIFICATION),
        ("effective_from", "2026-01-01T00:00:01Z"),
    ],
)
def test_content_identity_and_effective_time_match_explicit_source(tmp_path, field, value):
    bundle = policy_bundle()
    policy(bundle)["content"][field] = value
    rehash(policy(bundle))
    assert_rejected(tmp_path, bundle)


def test_equivalent_decimal_spellings_match_without_rewriting_original_content(tmp_path):
    bundle = policy_bundle()
    source = policy(bundle)
    source["content"]["wacc_base"] = "1e-1"
    source["parameter_records"][0]["value"] = 0.1
    bundle["inputs"]["wacc"]["value"] = "0.100"
    rehash(source)
    result = workspace.import_bundle(tmp_path / "research.sqlite", bundle)
    assert result["bundle"] == bundle
    assert result["valuation"]["parameters"]["wacc"] == "0.100"


def test_parameter_matching_uses_parameter_name_and_inclusive_creation_bounds(tmp_path):
    bundle = policy_bundle()
    source = policy(bundle)
    source["parameter_records"][0]["created_at"] = source["created_at"]
    source["parameter_records"][1]["created_at"] = source["observed_at"]
    source["parameter_records"].reverse()
    result = workspace.import_bundle(tmp_path / "research.sqlite", bundle)
    assert result["bundle"] == bundle
    assert result["valuation"]["parameters"]["wacc"] == "0.10"
    assert result["valuation"]["parameters"]["terminal_growth"] == "0.02"


def test_unused_internal_artifact_is_rejected(tmp_path):
    bundle = policy_bundle()
    for name in ("wacc", "terminal_growth"):
        bundle["inputs"][name]["source_ids"] = ["issuer_2024"]
    assert_rejected(tmp_path, bundle)


def test_multiple_internal_artifacts_cannot_jointly_cite_a_rate(tmp_path):
    bundle = policy_bundle()
    second = copy.deepcopy(policy(bundle))
    second["id"] = "second_internal_policy"
    bundle["sources"].append(second)
    bundle["inputs"]["wacc"]["source_ids"].append(second["id"])
    assert_rejected(tmp_path, bundle)


def test_each_rate_can_use_its_own_single_artifact(tmp_path):
    bundle = policy_bundle()
    second = copy.deepcopy(policy(bundle))
    second["id"] = "second_internal_policy"
    bundle["sources"].append(second)
    bundle["inputs"]["terminal_growth"]["source_ids"] = [second["id"]]
    result = workspace.import_bundle(tmp_path / "research.sqlite", bundle)
    assert result["valuation"]["status"] == "available"


@pytest.mark.parametrize("internal_rate", [None, "wacc", "terminal_growth"])
def test_external_only_rates_and_one_internal_rate_remain_supported(tmp_path, internal_rate):
    bundle = policy_bundle()
    for name in ("wacc", "terminal_growth"):
        if name != internal_rate:
            bundle["inputs"][name]["source_ids"] = ["issuer_2024"]
    if internal_rate is None:
        bundle["sources"].pop()
    result = workspace.import_bundle(tmp_path / "research.sqlite", bundle)
    assert result["valuation"]["status"] == "available"
    assert result["source_verification"] == "asserted_unverified"
    assert all(result[key] is False for key in VINTAGE_FLAGS)


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "internal_policy_artifact"),
        ("kind", None),
        ("url", "file:///etc/passwd"),
        ("url", "https://user:password@example.com"),
        ("published_at", None),
        ("published_at", "2026-01-05T00:00:00Z"),
        ("retrieved_at", "2024-05-31T00:00:00Z"),
        ("retrieved_at", "2999-01-01T00:00:00Z"),
        ("sha256", "A" * 64),
        ("extra", True),
    ],
)
def test_schema_two_external_documents_keep_existing_guards(tmp_path, field, value):
    bundle = policy_bundle()
    bundle["sources"][0][field] = value
    assert_rejected(tmp_path, bundle)


def test_external_retrieval_after_cutoff_stays_allowed_and_unverified(tmp_path):
    bundle = policy_bundle()
    bundle["sources"][0]["retrieved_at"] = "2026-01-05T00:00:00Z"
    result = workspace.import_bundle(tmp_path / "research.sqlite", bundle)
    assert result["source_vintages_verified"] is False
    assert result["bundle"]["sources"][0]["retrieved_at"] > result["as_of"]


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b.pop("economic_as_of"),
        lambda b: b.update(schema_version=True),
        lambda b: b.update(schema_version=2.0),
        lambda b: b.update(schema_version="2"),
        lambda b: b.update(schema_version=3),
        lambda b: b["sources"][0].pop("kind"),
        lambda b: b["sources"].append(copy.deepcopy(b["sources"][1])),
        lambda b: b["sources"][1].update(id="issuer_2024"),
        lambda b: b.update(data_kind="historical_oos"),
        lambda b: b["assumptions"].update(classification="historical_oos"),
    ],
)
def test_schema_two_bundle_and_source_discriminators_are_strict(tmp_path, change):
    bundle = policy_bundle()
    change(bundle)
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b.update(economic_as_of=b["as_of"]),
        lambda b: b["sources"][0].update(kind="external_document"),
        lambda b: b["sources"].append(policy_source()),
    ],
)
def test_schema_one_does_not_silently_adopt_schema_two_fields(tmp_path, change):
    bundle = legacy_bundle()
    change(bundle)
    assert_rejected(tmp_path, bundle)


@pytest.mark.parametrize("field", ["content_sha256", "assumption_set_id", "record_id", "wacc_base"])
def test_schema_two_json_duplicate_policy_keys_are_rejected(field):
    encoded = canonical(policy_bundle())
    prefix = json.dumps(field) + ":"
    assert prefix in encoded
    encoded = encoded.replace(prefix, prefix + "null," + prefix, 1)
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        workspace.parse_bundle_json(encoded)


def test_invalid_policy_import_does_not_change_a_preexisting_legacy_store(tmp_path):
    database = tmp_path / "mixed.sqlite"
    original = workspace.import_bundle(database, legacy_bundle())
    before = database.read_bytes()
    malformed = policy_bundle()
    policy(malformed)["historical_available_at"] = "2022-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        workspace.import_bundle(database, malformed)
    assert database.read_bytes() == before
    assert workspace.list_runs(database) == [original]


def forge_result(database: Path, run_id: str, field: str, value: Any) -> None:
    with sqlite3.connect(database) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='research_runs_no_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER research_runs_no_update")
        saved = json.loads(
            connection.execute(
                "SELECT result_json FROM research_runs WHERE run_id=?", (run_id,)
            ).fetchone()[0]
        )
        saved[field] = value
        encoded = canonical(saved)
        connection.execute(
            "UPDATE research_runs SET result_json=?,result_hash=? WHERE run_id=?",
            (encoded, digest(encoded), run_id),
        )
        connection.execute(trigger)


@pytest.mark.parametrize(
    "field,value",
    [
        *((key, True) for key in VINTAGE_FLAGS),
        ("formal_decision", "buy"),
        ("source_verification", "verified"),
        ("classification", "historical_oos"),
        ("economic_as_of", "2025-01-01T00:00:00Z"),
        ("provenance_limitations", []),
        ("schema_version", 1),
    ],
)
def test_rehashed_output_forgery_rejected_on_read_and_before_mixed_store_append(
    tmp_path, field, value
):
    database = tmp_path / "research.sqlite"
    workspace.import_bundle(database, legacy_bundle())
    result = workspace.import_bundle(database, policy_bundle())
    forge_result(database, result["run_id"], field, value)
    before = database.read_bytes()
    with pytest.raises(ValueError, match="content or identity mismatch"):
        workspace.load_run(database, result["run_id"])
    with pytest.raises(ValueError, match="content or identity mismatch"):
        workspace.list_runs(database)
    for bundle in (legacy_bundle(), policy_bundle()):
        with pytest.raises(ValueError, match="content or identity mismatch"):
            workspace.import_bundle(database, bundle)
    assert database.read_bytes() == before


@pytest.mark.parametrize("column", ["result_hash", "input_hash", "generated_at"])
def test_schema_two_row_integrity_is_checked_on_replay(tmp_path, column):
    database = tmp_path / "research.sqlite"
    result = workspace.import_bundle(database, policy_bundle())
    with sqlite3.connect(database) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='research_runs_no_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER research_runs_no_update")
        connection.execute(f"UPDATE research_runs SET {column}=?", ("0" * 64,))
        connection.execute(trigger)
    before = database.read_bytes()
    with pytest.raises(ValueError):
        workspace.load_run(database, result["run_id"])
    with pytest.raises(ValueError):
        workspace.import_bundle(database, policy_bundle())
    assert database.read_bytes() == before


def test_schema_two_never_adopts_or_mutates_formal_database(tmp_path):
    database = tmp_path / "formal.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE formal_decisions (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO formal_decisions VALUES (1)")
    before = database.read_bytes()
    with pytest.raises(ValueError):
        workspace.import_bundle(database, policy_bundle())
    assert database.read_bytes() == before
