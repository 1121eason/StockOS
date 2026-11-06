import json

import pytest

from valuation_engine.ai.quarter_package import VERSION, build_package


def prepared(*, available_at="2022-08-25T13:30:00+00:00", source_hash="a" * 64):
    cutoff = "2022-08-25T13:30:00+00:00"
    return {
        "quant_context": {
            "quarter": "FY2023-Q2",
            "as_of_timestamp": cutoff,
            "information_cutoff": cutoff,
            "forecast_run_id": 7,
            "quant_forecasts": [{"period_type": "quarter", "revenue": "12.3"}],
            "fundamental_features": {"growth": "0.4"},
            "quant_guidance_accuracy": {"revenue": {"samples": []}},
            "regime": {"forecast_run_id": 7, "as_of": cutoff, "confirmed_regime": "Growth"},
        },
        "sources": {
            "documents": [
                {
                    "source_document_id": 11,
                    "source_hash": source_hash,
                    "document_type": "Earnings Release",
                    "source_url": "https://nvidianews.nvidia.com/release",
                    "published_at": cutoff,
                    "available_at": available_at,
                    "timestamp_precision": "exact",
                    "availability_evidence_id": 3,
                }
            ],
            "blocks": [
                {
                    "block_id": "11:abc",
                    "source_document_id": 11,
                    "source_hash": source_hash,
                    "available_at": available_at,
                    "section": "Demand",
                    "text": "Demand remains strong across our largest customers.",
                    "speaker": None,
                    "speaker_role": None,
                }
            ],
            "excluded_blocks": [],
        },
    }


def test_package_has_deterministic_manifest_and_single_quarter_inputs():
    first = build_package(prepared())
    second = build_package(prepared())
    assert first == second
    assert first["manifest"]["package_version"] == VERSION
    assert first["manifest"]["quarter"] == "FY2023-Q2"
    assert first["manifest"]["block_count"] == 1
    assert "input/regime.json" in first["files"]
    manifest = json.loads(first["files"]["input/source_manifest.json"])
    assert manifest["sources"][0]["source_hash"] == "a" * 64
    assert manifest["sources"][0]["blocks"][0]["block_id"] == "11:abc"
    assert not any("price" in path or "return" in path for path in first["files"])


def test_package_rejects_future_sources_and_context():
    with pytest.raises(ValueError, match="after PIT cutoff"):
        build_package(prepared(available_at="2022-08-25T13:31:00+00:00"))
    context = prepared()
    context["quant_context"]["regime"]["as_of"] = "2022-08-25T13:31:00+00:00"
    with pytest.raises(ValueError, match="Regime output became available"):
        build_package(context)


def test_package_rejects_source_hash_or_availability_drift():
    context = prepared()
    context["sources"]["blocks"][0]["source_hash"] = "b" * 64
    with pytest.raises(ValueError, match="does not match a manifest source"):
        build_package(context)
    context = prepared()
    context["sources"]["blocks"][0]["available_at"] = "2022-08-25T13:31:00+00:00"
    with pytest.raises(ValueError, match="after PIT cutoff"):
        build_package(context)
