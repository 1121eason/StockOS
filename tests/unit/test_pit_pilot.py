import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import get_args

from test_quarter_package import prepared

from valuation_engine.ai.contracts import FeatureName
from valuation_engine.ai.pilot import assess_single_quarter
from valuation_engine.ai.quarter_package import build_package


def ready_case():
    context = prepared()
    context["quant_context"]["anomaly_codes"] = []
    context["sources"]["blocks"].append(
        {
            "block_id": "11:def",
            "source_document_id": 11,
            "source_hash": "a" * 64,
            "available_at": "2022-08-25T13:30:00+00:00",
            "section": "Management",
            "text": "The company expects broad customer demand to remain durable.",
            "speaker": None,
            "speaker_role": None,
        }
    )
    context["quarter_package_manifest"] = build_package(context)["manifest"]
    run = SimpleNamespace(
        quarter="FY2023-Q2",
        source_document_ids=[11],
        information_cutoff=datetime(2022, 8, 25, 13, 30, tzinfo=UTC),
        context_json=context,
    )
    evidence = [
        SimpleNamespace(
            id=1,
            evidence_key="0:admitted",
            source_document_id=11,
            source_hash="a" * 64,
            block_id="11:abc",
            span="Demand remains strong across our largest customers.",
            span_hash=hashlib.sha256(
                b"Demand remains strong across our largest customers."
            ).hexdigest(),
            available_at=run.information_cutoff,
            speaker=None,
            metadata_json={"speaker_status": "unknown", "speaker_role": None},
        )
    ]
    present = {"demand_momentum"}
    primary = (
        "demand_momentum",
        "pricing_power",
        "supply_constraint",
        "product_cycle_strength",
        "competition_outlook",
        "customer_financing_quality",
        "working_capital_quality",
        "regulatory_outlook",
        "management_confidence",
        "guidance_visibility",
        "structural_outlook",
    )
    snapshot = SimpleNamespace(
        metadata_json={
            "features": {"demand_momentum": 0.5},
            "missing_features": sorted(set(get_args(FeatureName)) - present),
            "sections": {},
        },
        **{name: None for name in primary},
    )
    feature = SimpleNamespace(
        feature_name="demand_momentum", metadata_json={"evidence_keys": ["0:admitted"]}
    )
    challenges = [
        SimpleNamespace(kind=kind, evidence_ids=[1], metadata_json={"anomaly_code": None, "evidence_ids": [1]})
        for kind in ("upside", "downside", "regime")
    ]
    calls = [SimpleNamespace(status="valid") for _ in range(5)]
    rejected = [
        SimpleNamespace(
            reason="unsupported_speaker",
            raw_claim={
                "key": "rejected",
                "block_id": "11:def",
                "span": "The company expects broad customer demand to remain durable.",
                "speaker": "Jensen Huang",
                "speaker_status": "verified",
            },
        )
    ]
    return run, snapshot, calls, evidence, [feature], challenges, rejected


def test_quarantined_speaker_rejection_does_not_fail_complete_supported_quarter():
    result = assess_single_quarter(*ready_case())
    assert result["gate"] == "PASS"
    assert result["quarantined_rejections"] == 1
    assert result["rejection_reasons"] == {"unsupported_speaker": 1}


def test_rejected_attribution_cannot_reenter_formal_evidence():
    case = ready_case()
    case[3][0].block_id = "11:def"
    case[3][0].span = case[6][0].raw_claim["span"]
    case[3][0].speaker = "Jensen Huang"
    case[3][0].metadata_json = {"speaker_status": "verified", "speaker_role": None}
    result = assess_single_quarter(*case)
    assert result["gate"] == "FAIL"
    assert "rejected_attribution_reentered_formal_evidence" in result["blockers"]


def test_future_or_unknown_rejection_reason_fails_closed():
    case = ready_case()
    case[6][0].reason = "unknown_or_future_block"
    result = assess_single_quarter(*case)
    assert result["gate"] == "FAIL"
    assert "non_quarantinable_rejection:unknown_or_future_block" in result["blockers"]


def test_missing_mandatory_challenge_blocks_quarter():
    case = ready_case()
    case = (*case[:5], [challenge for challenge in case[5] if challenge.kind != "downside"], case[6])
    result = assess_single_quarter(*case)
    assert result["gate"] == "FAIL"
    assert "mandatory_challenge_missing" in result["blockers"]


def test_nonliteral_source_span_rejection_remains_a_pilot_blocker():
    case = ready_case()
    case[6][0].reason = "span_not_in_source"
    result = assess_single_quarter(*case)
    assert result["gate"] == "FAIL"
    assert "non_quarantinable_rejection:span_not_in_source" in result["blockers"]


def overlong_case():
    case = ready_case()
    long_span = " ".join(["firm"] * 81)
    case[0].context_json["sources"]["blocks"][1]["text"] = long_span
    case[0].context_json["quarter_package_manifest"] = build_package(case[0].context_json)[
        "manifest"
    ]
    case[6][0].reason = "evidence_span_too_long"
    case[6][0].raw_claim = {"block_id": "11:def", "span": long_span}
    return case


def test_verified_overlong_candidate_is_quarantined_without_failing_complete_quarter():
    result = assess_single_quarter(*overlong_case())
    assert result["gate"] == "PASS"
    assert result["rejection_reasons"] == {"evidence_span_too_long": 1}


def test_short_or_unknown_overlong_rejection_does_not_bypass_gate():
    case = overlong_case()
    case[6][0].raw_claim["span"] = "firm firm"
    result = assess_single_quarter(*case)
    assert result["gate"] == "FAIL"
    assert "overlong_rejection_not_verified" in result["blockers"]
    case = overlong_case()
    case[6][0].raw_claim["block_id"] = "missing"
    result = assess_single_quarter(*case)
    assert result["gate"] == "FAIL"
    assert "overlong_rejection_not_verified" in result["blockers"]


def test_rejected_overlong_span_cannot_reenter_formal_evidence():
    case = overlong_case()
    case[3][0].block_id = "11:def"
    case[3][0].span = case[6][0].raw_claim["span"]
    result = assess_single_quarter(*case)
    assert result["gate"] == "FAIL"
    assert "rejected_span_reentered_formal_evidence" in result["blockers"]
