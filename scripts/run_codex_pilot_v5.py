"""One explicit FY2023-Q2 rerun using the PITQuarterPackageV1 contract."""

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from valuation_engine.ai.attempt_journal import (
    AttemptJournal,
    workspace_fingerprint,
    write_immutable_json,
)
from valuation_engine.ai.cli_provider import CodexCLIProvider
from valuation_engine.ai.codex_pit import (
    DISABLED,
    MODEL,
    POLICY,
    POLICY_HASH,
    VERSION,
    require_valid_gate,
)
from valuation_engine.ai.contracts import POLICY_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from valuation_engine.ai.pilot import assess_single_quarter
from valuation_engine.ai.provider import ProviderUnavailable
from valuation_engine.ai.quarter_package import VERSION as PACKAGE_VERSION
from valuation_engine.ai.quarter_package import build_package
from valuation_engine.ai.service import analyze, prepare
from valuation_engine.config import Settings
from valuation_engine.db.schema import (
    AIAnalysisRun,
    AIAnalystFeature,
    AIChallenge,
    AIEvidence,
    AIProviderCall,
    AIUnsupportedClaim,
    FinancialFact,
    ForecastPeriod,
    ForecastRun,
    GuidanceItem,
    QuantFeature,
    QuarterlySnapshot,
    RegimeSnapshot,
    RegimeTransition,
    SegmentFact,
    ValuationSnapshot,
)
from valuation_engine.db.session import engine
from valuation_engine.db.store import digest
from valuation_engine.quant.ai_context import resolve_run

OUT = Path("data/m41/codex")
TABLES = (
    FinancialFact,
    SegmentFact,
    GuidanceItem,
    QuarterlySnapshot,
    QuantFeature,
    ForecastRun,
    ForecastPeriod,
    RegimeSnapshot,
    RegimeTransition,
    ValuationSnapshot,
)

EXPECTED_Q2_INPUTS = {
    "quarter": "FY2023-Q2",
    "information_cutoff": "2022-08-25T13:30:00+00:00",
    "source_document_ids": [9, 10, 107, 108],
    "package_version": "PITQuarterPackageV1",
    "source_count": 4,
    "block_count": 932,
    "package_hash": "331e90ebd3ca261c06cf090a5d46ae852a4ded7eb133c434e5f7537abd3ff4c5",
    "policy_version": "AIAnalystPolicyV3",
    "prompt_version": "PromptSetV5",
    "schema_version": "FeatureSchemaV2",
    "requested_model": "gpt-6-astra",
}
EXPECTED_CASES = frozenset("ABCDEFG")
NATIVE_KERNEL_PROBES = ("file", "repository", "write", "network")


def _is_sha256(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def normalize_source_ids(source_ids):
    if all(isinstance(value, int) and not isinstance(value, bool) for value in source_ids):
        return sorted(source_ids)
    return sorted(source_ids, key=lambda value: (type(value).__name__, str(value)))


def normalized_receipt_path(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return str(Path(value).expanduser().resolve())
    except (OSError, RuntimeError):
        return None


def read_explicit_receipt(path):
    """Read only the path supplied by the caller and pin its exact bytes by hash."""
    resolved = Path(path).expanduser().resolve()
    reference = {"path": str(resolved), "sha256": None, "error_type": None}
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        reference["error_type"] = type(exc).__name__
        return reference, None
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        reference["error_type"] = type(exc).__name__
        return reference, None
    if not isinstance(value, dict):
        reference["error_type"] = "InvalidReceiptShape"
        return reference, None
    return reference, value


def verify_kernel_receipt_binding(
    declared, explicit_reference, *, declared_present=True
):
    """Bind the saved isolation receipt to the exact explicit kernel file bytes."""
    blockers = []
    explicit_path = normalized_receipt_path(
        explicit_reference.get("path") if isinstance(explicit_reference, dict) else None
    )
    declared_path = normalized_receipt_path(
        declared.get("path") if isinstance(declared, dict) else None
    )
    explicit_sha256 = (
        explicit_reference.get("sha256") if isinstance(explicit_reference, dict) else None
    )
    declared_sha256 = declared.get("sha256") if isinstance(declared, dict) else None
    actual_sha256 = None
    read_error_type = None
    if not declared_present:
        blockers.append("isolation_kernel_receipt_missing")
    elif (
        not isinstance(declared, dict)
        or declared_path is None
        or not _is_sha256(declared_sha256)
        or declared.get("error_type") is not None
    ):
        blockers.append("isolation_kernel_receipt_malformed")
    if declared_path is not None and explicit_path is not None and declared_path != explicit_path:
        blockers.append("isolation_kernel_receipt_path_mismatch")
    try:
        if explicit_path is not None:
            actual_sha256 = hashlib.sha256(Path(explicit_path).read_bytes()).hexdigest()
        else:
            read_error_type = "ExplicitKernelReceiptPathInvalid"
    except OSError as exc:
        read_error_type = type(exc).__name__
    if read_error_type is not None or not _is_sha256(actual_sha256):
        blockers.append("explicit_kernel_receipt_unreadable")
    elif actual_sha256 != explicit_sha256:
        blockers.append("explicit_kernel_receipt_changed_after_read")
    if not _is_sha256(explicit_sha256) or declared_sha256 != explicit_sha256:
        blockers.append("isolation_kernel_receipt_hash_mismatch")
    return {
        "status": "PASS" if not blockers else "FAIL",
        "expected": {"path": explicit_path, "sha256": explicit_sha256},
        "actual": {
            "declared": declared,
            "normalized_declared_path": declared_path,
            "normalized_explicit_path": explicit_path,
            "declared_sha256": declared_sha256,
            "actual_bytes_sha256": actual_sha256,
            "read_error_type": read_error_type,
        },
        "blockers": sorted(set(blockers)),
    }


def verify_saved_isolation(isolation_ref, gate, kernel_ref, kernel):
    """Require the exact C1-C12 receipt plus hash-bearing native kernel probes."""
    blockers = []
    discovery_reference = gate.get("discovery_receipt") if isinstance(gate, dict) else None
    if isinstance(discovery_reference, dict) and isinstance(discovery_reference.get("path"), str):
        observed_discovery_ref, discovery = read_explicit_receipt(discovery_reference["path"])
    else:
        observed_discovery_ref, discovery = (
            {"path": None, "sha256": None, "error_type": "DiscoveryReceiptReferenceMissing"},
            None,
        )
    kernel_reference = gate.get("kernel_receipt") if isinstance(gate, dict) else None
    kernel_binding = verify_kernel_receipt_binding(
        kernel_reference,
        kernel_ref,
        declared_present=isinstance(gate, dict) and "kernel_receipt" in gate,
    )
    expected = {
        "gate": "PASS",
        "result": "PIT_TRANSPORT_VERIFIED",
        "gates": {f"C{i}": "PASS" for i in range(1, 13)},
        "case_ids": sorted(EXPECTED_CASES),
        "kernel_probes": list(NATIVE_KERNEL_PROBES),
        "policy_hash": POLICY_HASH,
        "cli_version": VERSION,
        "requested_model": MODEL,
        "kernel_receipt": kernel_binding["expected"],
        "discovery": {
            "authenticated": True,
            "required_flags_supported": True,
            "features_verified": True,
            "reason": "PIT_PROBES_REQUIRED",
            "disabled_feature_flags": {
                name: "false" for name in DISABLED if name != "unified_exec"
            },
            "skip_host_skill_discovery": "true",
        },
        "historical_data_sent": False,
    }
    actual = {
        "isolation_receipt": isolation_ref,
        "kernel_receipt": kernel_ref,
        "gate": gate.get("gate") if isinstance(gate, dict) else None,
        "result": gate.get("result") if isinstance(gate, dict) else None,
        "gates": gate.get("gates") if isinstance(gate, dict) else None,
        "policy_hash": gate.get("policy_hash") if isinstance(gate, dict) else None,
        "transport_policy": gate.get("transport_policy") if isinstance(gate, dict) else None,
        "model": gate.get("model") if isinstance(gate, dict) else None,
        "historical_data_sent": gate.get("historical_data_sent") if isinstance(gate, dict) else None,
        "case_ids": sorted(
            (case.get("case") for case in gate.get("cases", []) if isinstance(case, dict)),
            key=lambda value: str(value),
        ) if isinstance(gate, dict) and isinstance(gate.get("cases"), list) else [],
        "kernel_gate": kernel.get("gate") if isinstance(kernel, dict) else None,
        "kernel_policy_hash": kernel.get("policy_hash") if isinstance(kernel, dict) else None,
        "kernel_cli_version": kernel.get("cli_version") if isinstance(kernel, dict) else None,
        "kernel_receipt_binding": kernel_binding["actual"],
        "discovery_receipt": {
            "declared": discovery_reference,
            "observed": observed_discovery_ref,
        },
        "discovery": {
            key: discovery.get(key) if isinstance(discovery, dict) else None
            for key in (
                "cli_version",
                "requested_model",
                "authenticated",
                "required_flags_supported",
                "features_verified",
                "reason",
                "effective_feature_flags",
            )
        },
        "kernel_probes": {},
    }
    for reference, name in ((isolation_ref, "isolation_receipt"), (kernel_ref, "kernel_receipt")):
        if reference.get("error_type") or not _is_sha256(reference.get("sha256")):
            blockers.append(f"{name}_unreadable_or_unhashed")
    blockers.extend(kernel_binding["blockers"])
    if not isinstance(gate, dict):
        blockers.append("isolation_receipt_missing_or_invalid")
    else:
        try:
            require_valid_gate(gate)
        except ProviderUnavailable:
            blockers.append("c1_c12_contract_invalid")
        if gate.get("result") != "PIT_TRANSPORT_VERIFIED":
            blockers.append("isolation_result_not_verified")
        if (
            not isinstance(discovery_reference, dict)
            or discovery_reference.get("error_type") is not None
            or not _is_sha256(discovery_reference.get("sha256"))
            or observed_discovery_ref.get("sha256") != discovery_reference.get("sha256")
            or observed_discovery_ref.get("error_type") is not None
        ):
            blockers.append("isolation_discovery_receipt_missing_or_hash_mismatch")
        if isinstance(discovery, dict):
            if discovery.get("cli_version") != VERSION:
                blockers.append("saved_discovery_cli_version_mismatch")
            if discovery.get("requested_model") != MODEL:
                blockers.append("saved_discovery_model_mismatch")
            if discovery.get("authenticated") is not True:
                blockers.append("saved_discovery_not_authenticated")
            if discovery.get("required_flags_supported") is not True:
                blockers.append("saved_discovery_required_flags_missing")
            if discovery.get("features_verified") is not True:
                blockers.append("saved_discovery_features_not_verified")
            if discovery.get("reason") != "PIT_PROBES_REQUIRED":
                blockers.append("saved_discovery_reason_not_ready_for_pit")
            flags = discovery.get("effective_feature_flags", {})
            if not isinstance(flags, dict):
                flags = {}
            for name, value in expected["discovery"]["disabled_feature_flags"].items():
                if flags.get(name) != value:
                    blockers.append(f"saved_discovery_feature_{name}_not_disabled")
            if flags.get("skip_host_skill_discovery") != "true":
                blockers.append("saved_discovery_host_skill_discovery_not_disabled")
        else:
            blockers.append("saved_discovery_receipt_invalid")
        if not _is_sha256(gate.get("configuration_hash_before")) or (
            gate.get("configuration_hash_before") != gate.get("configuration_hash_after")
        ):
            blockers.append("isolation_configuration_hash_invalid")
        cases = gate.get("cases")
        if not isinstance(cases, list) or len(cases) != len(EXPECTED_CASES):
            blockers.append("isolation_case_set_incomplete")
            cases = []
        if actual["case_ids"] != sorted(EXPECTED_CASES):
            blockers.append("isolation_case_ids_mismatch")
        by_case = {
            case.get("case"): case
            for case in cases
            if isinstance(case, dict) and isinstance(case.get("case"), str)
        }
        if set(by_case) != EXPECTED_CASES:
            blockers.append("isolation_case_ids_mismatch")
        for case_id in sorted(EXPECTED_CASES):
            case = by_case.get(case_id, {})
            if (
                case.get("status") != "PASS"
                or case.get("failure_kind") is not None
                or case.get("exit_code") != 0
                or case.get("turn_completed") is not True
            ):
                blockers.append(f"isolation_case_{case_id}_not_completed")
            for key in ("raw_response_hash", "response_hash", "stderr_hash"):
                if not _is_sha256(case.get(key)):
                    blockers.append(f"isolation_case_{case_id}_{key}_missing")
            for key in (
                "external_network_success",
                "external_file_success",
                "external_connector_success",
                "external_future_fact_received",
                "permission_escalation_requested",
                "permission_escalation_granted",
            ):
                if case.get(key) != 0:
                    blockers.append(f"isolation_case_{case_id}_{key}_not_zero")
            metadata = case.get("metadata")
            working = (
                metadata.get("working_directory_receipt", {})
                if isinstance(metadata, dict)
                else {}
            )
            if not isinstance(working, dict):
                working = {}
            if (
                working.get("research_data") is not False
                or working.get("files_read_only") is not True
                or working.get("file_mode") != "0400"
                or working.get("directories_read_only_during_inference") is not True
            ):
                blockers.append(f"isolation_case_{case_id}_scratch_contract_invalid")
        if by_case.get("G", {}).get("structured_output") != {"answer": "unavailable"}:
            blockers.append("injected_instruction_case_not_unavailable")
    if not isinstance(kernel, dict):
        blockers.append("kernel_receipt_missing_or_invalid")
    else:
        if kernel.get("gate") != "PASS":
            blockers.append("kernel_native_gate_failed")
        if kernel.get("policy_hash") != POLICY_HASH:
            blockers.append("kernel_policy_hash_mismatch")
        if kernel.get("cli_version") != VERSION:
            blockers.append("kernel_cli_version_mismatch")
        for probe_name in NATIVE_KERNEL_PROBES:
            probe = kernel.get(probe_name, {})
            actual["kernel_probes"][probe_name] = {
                key: probe.get(key)
                for key in (
                    "denial_observed",
                    "diagnostic_class",
                    "exit_code",
                    "marker_not_returned",
                    "write_file_absent",
                    "stdout_hash",
                    "stderr_hash",
                )
            }
            if (
                probe.get("denial_observed") is not True
                or probe.get("marker_not_returned") is not True
                or probe.get("write_file_absent") is not True
                or not isinstance(probe.get("exit_code"), int)
                or probe.get("exit_code") == 0
                or not _is_sha256(probe.get("stdout_hash"))
                or not _is_sha256(probe.get("stderr_hash"))
            ):
                blockers.append(f"kernel_{probe_name}_probe_not_proven")
    return {
        "status": "PASS" if not blockers else "FAIL",
        "expected": expected,
        "actual": actual,
        "blockers": sorted(set(blockers)),
    }


def verify_live_isolation(capability, gate, current_config_hash):
    """Bind current CLI/auth/effective flags/config to the saved synthetic evidence."""
    flags = capability.get("effective_feature_flags", {}) if isinstance(capability, dict) else {}
    if not isinstance(flags, dict):
        flags = {}
    expected_false = sorted(name for name in DISABLED if name != "unified_exec")
    expected = {
        "cli_version": VERSION,
        "requested_model": MODEL,
        "authenticated": True,
        "required_flags_supported": True,
        "features_verified": True,
        "reason": "PIT_PROBES_REQUIRED",
        "disabled_feature_flags": {name: "false" for name in expected_false},
        "skip_host_skill_discovery": "true",
        "configuration_hash": gate.get("configuration_hash_before") if isinstance(gate, dict) else None,
        "policy_hash": POLICY_HASH,
    }
    actual = {
        "cli_version": capability.get("cli_version") if isinstance(capability, dict) else None,
        "requested_model": capability.get("requested_model") if isinstance(capability, dict) else None,
        "authenticated": capability.get("authenticated") if isinstance(capability, dict) else None,
        "required_flags_supported": capability.get("required_flags_supported") if isinstance(capability, dict) else None,
        "features_verified": capability.get("features_verified") if isinstance(capability, dict) else None,
        "reason": capability.get("reason") if isinstance(capability, dict) else None,
        "effective_feature_flags": flags,
        "configuration_hash": current_config_hash,
        "policy_hash": gate.get("policy_hash") if isinstance(gate, dict) else None,
    }
    blockers = []
    for key in ("cli_version", "requested_model", "authenticated", "required_flags_supported", "features_verified", "reason"):
        if actual[key] != expected[key]:
            blockers.append(f"live_{key}_mismatch")
    if not isinstance(gate, dict) or actual["policy_hash"] != expected["policy_hash"]:
        blockers.append("live_policy_hash_mismatch")
    if (
        not isinstance(gate, dict)
        or gate.get("configuration_hash_before") != gate.get("configuration_hash_after")
        or current_config_hash != gate.get("configuration_hash_before")
    ):
        blockers.append("current_configuration_hash_mismatch")
    for name, value in expected["disabled_feature_flags"].items():
        if flags.get(name) != value:
            blockers.append(f"effective_feature_{name}_not_disabled")
    if flags.get("skip_host_skill_discovery") != "true":
        blockers.append("effective_host_skill_discovery_not_disabled")
    return {
        "status": "PASS" if not blockers else "FAIL",
        "expected": expected,
        "actual": actual,
        "blockers": sorted(set(blockers)),
    }


def verify_q2_inputs(context, *, expected_prompt_version=None):
    """Rebuild the package manifest and compare every approved Q2 input before inference."""
    expected_inputs = dict(EXPECTED_Q2_INPUTS)
    if expected_prompt_version is not None:
        expected_inputs["prompt_version"] = expected_prompt_version
    mismatches = {}
    quant = context.get("quant_context", {}) if isinstance(context, dict) else {}
    sources = context.get("sources", {}) if isinstance(context, dict) else {}
    docs = sources.get("documents", []) if isinstance(sources, dict) else []
    source_ids = [doc.get("source_document_id") for doc in docs if isinstance(doc, dict)]
    normalized_ids = normalize_source_ids(source_ids)
    stored_manifest = context.get("quarter_package_manifest") if isinstance(context, dict) else None
    try:
        computed_manifest = build_package(context)["manifest"]
        actual = {
            "quarter": quant.get("quarter"),
            "information_cutoff": quant.get("information_cutoff"),
            "source_document_ids": normalized_ids,
            "package_version": computed_manifest.get("package_version"),
            "source_count": computed_manifest.get("source_count"),
            "block_count": computed_manifest.get("block_count"),
            "package_hash": computed_manifest.get("package_hash"),
            "policy_version": POLICY_VERSION,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "requested_model": MODEL,
        }
        if len(source_ids) != len(set(source_ids)):
            mismatches["source_document_ids"] = {
                "expected": expected_inputs["source_document_ids"],
                "actual": normalized_ids,
                "reason": "duplicate_source_id",
            }
        if not isinstance(stored_manifest, dict) or stored_manifest != computed_manifest:
            mismatches["stored_package_manifest"] = {
                "expected_sha256": digest(computed_manifest),
                "actual_sha256": digest(stored_manifest) if isinstance(stored_manifest, dict) else None,
            }
    except (KeyError, TypeError, ValueError) as exc:
        actual = {"package_build_error_type": type(exc).__name__}
        mismatches["package"] = {"expected": expected_inputs, "actual": actual}
    if "information_cutoff" in actual and hasattr(actual["information_cutoff"], "isoformat"):
        actual["information_cutoff"] = actual["information_cutoff"].isoformat()
    for key, expected_value in expected_inputs.items():
        actual_value = actual.get(key)
        if actual_value != expected_value and key not in mismatches:
            mismatches[key] = {"expected": expected_value, "actual": actual_value}
    return compare_q2_input_summary(
        actual, mismatches=mismatches, expected_prompt_version=expected_prompt_version
    )


def compare_q2_input_summary(actual, *, mismatches=None, expected_prompt_version=None):
    """Compare a prepared package summary with the immutable approved Q2 values."""
    expected_inputs = dict(EXPECTED_Q2_INPUTS)
    if expected_prompt_version is not None:
        expected_inputs["prompt_version"] = expected_prompt_version
    mismatches = dict(mismatches or {})
    for key, expected_value in expected_inputs.items():
        actual_value = actual.get(key) if isinstance(actual, dict) else None
        if actual_value != expected_value and key not in mismatches:
            mismatches[key] = {"expected": expected_value, "actual": actual_value}
    blockers = ["approved_q2_input_mismatch"] if mismatches else []
    return {
        "status": "PASS" if not blockers else "FAIL",
        "expected": expected_inputs,
        "actual": actual,
        "mismatches": mismatches,
        "blockers": blockers,
    }


def execute_after_preflight(preflight, execute):
    """Fail closed so no historical callback runs unless the whole preflight passed."""
    if preflight.get("status") != "PASS" or preflight.get("blockers"):
        raise SystemExit("Q2 preflight failed; historical model call was not started")
    return execute()


def analyze_approved_context(db, quant, provider, raw_dir, context, context_hash):
    """Use the runner-approved context for the actual service analysis."""
    return analyze(
        db,
        quant,
        provider,
        raw_dir,
        refresh=True,
        prepared_context=context,
        approved_context_hash=context_hash,
    )


def current_user_config_hash():
    path = Path.home() / ".codex/config.toml"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def receipt_references_unchanged(*references):
    results = []
    for reference in references:
        current_hash = None
        error_type = None
        try:
            current_hash = hashlib.sha256(Path(reference["path"]).read_bytes()).hexdigest()
        except OSError as exc:
            error_type = type(exc).__name__
        results.append(
            {
                "path": reference.get("path"),
                "expected_sha256": reference.get("sha256"),
                "actual_sha256": current_hash,
                "error_type": error_type,
                "unchanged": current_hash == reference.get("sha256")
                and _is_sha256(current_hash),
            }
        )
    return {
        "status": "PASS" if results and all(row["unchanged"] for row in results) else "FAIL",
        "receipts": results,
        "blockers": []
        if results and all(row["unchanged"] for row in results)
        else ["explicit_receipt_changed_or_unreadable"],
    }


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolation-receipt", required=True, type=Path)
    parser.add_argument("--kernel-receipt", required=True, type=Path)
    return parser


def save(path, value):
    write_immutable_json(path, value)


def preservation_hashes(db):
    result = {}
    for model in TABLES:
        rows = [
            {column.name: getattr(row, column.key) for column in model.__table__.columns}
            for row in db.scalars(select(model).order_by(model.id))
        ]
        result[model.__tablename__] = {
            "count": len(rows),
            "content_hash": digest(rows),
        }
    return result


def main(
    argv=None,
    *,
    expected_prompt_version=None,
    purpose="codex_pit_q2_v5_pilot",
    activation="single_quarter_pilot_v5",
):
    args = argument_parser().parse_args(argv)
    isolation_ref, gate = read_explicit_receipt(args.isolation_receipt)
    kernel_ref, kernel = read_explicit_receipt(args.kernel_receipt)
    journal = AttemptJournal(
        OUT / "attempts",
        purpose=purpose,
        manifest={
            "git": workspace_fingerprint(Path.cwd()),
            "provider": "codex_cli",
            "requested_model": MODEL,
            "transport_policy": POLICY,
            "transport_policy_hash": POLICY_HASH,
            "policy_version": POLICY_VERSION,
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "quarter_package_version": PACKAGE_VERSION,
            "isolation_receipt": isolation_ref,
            "kernel_receipt": kernel_ref,
        },
    )
    outcome = "failed"
    error_type = None
    try:
        journal.emit("runner_started", stage="pilot", status="started", pid=os.getpid())
        receipt_path = journal.path / "pilot.json"
        context_path = journal.path / "context.json"
        preservation_path = journal.path / "preservation.json"
        isolation_check_path = journal.path / "isolation-check.json"
        input_check_path = journal.path / "input-check.json"
        live_check_path = journal.path / "live-isolation-check.json"
        receipt_check_path = journal.path / "receipt-integrity-check.json"
        preflight_path = journal.path / "preflight.json"
        isolation_check = verify_saved_isolation(isolation_ref, gate, kernel_ref, kernel)
        save(isolation_check_path, isolation_check)
        journal.emit(
            "stage_completed",
            stage="saved_isolation_evidence",
            status=isolation_check["status"].lower(),
            blocker_count=len(isolation_check["blockers"]),
        )
        if isolation_check["status"] != "PASS":
            raise SystemExit("Saved C1-C12/native isolation evidence failed closed")
        settings = Settings()
        with Session(engine(settings.qve_database_url)) as db:
            quant = resolve_run(db, 1, "FY2023-Q2")
            context = prepare(db, quant, settings.qve_raw_dir)
            approved_context_hash = digest(context)
            input_check = verify_q2_inputs(context, expected_prompt_version=expected_prompt_version)
            save(input_check_path, input_check)
            journal.emit(
                "stage_completed",
                stage="approved_q2_inputs",
                status=input_check["status"].lower(),
                blocker_count=len(input_check["blockers"]),
            )
            if input_check["status"] != "PASS":
                raise SystemExit("Approved FY2023-Q2 inputs changed; historical call was not started")

            provider = CodexCLIProvider(MODEL, timeout=180)
            capability = provider.check()
            save(journal.path / "provider-check.json", capability)
            journal.emit(
                "provider_checked",
                stage="discovery",
                status="passed" if capability.get("reason") == "PIT_PROBES_REQUIRED" else "failed",
                reason=capability.get("reason"),
                cli_version=capability.get("cli_version"),
            )
            current_config_hash = current_user_config_hash()
            live_check = verify_live_isolation(capability, gate, current_config_hash)
            save(live_check_path, live_check)
            if live_check["status"] != "PASS":
                raise SystemExit("Live CLI/configuration isolation differs from saved evidence")

            saved_discovery_ref = (
                gate.get("discovery_receipt") if isinstance(gate, dict) else None
            )
            receipt_check = receipt_references_unchanged(
                isolation_ref,
                kernel_ref,
                saved_discovery_ref if isinstance(saved_discovery_ref, dict) else {},
            )
            save(receipt_check_path, receipt_check)
            preflight = {
                "status": "PASS"
                if receipt_check["status"] == "PASS"
                and isolation_check["status"] == "PASS"
                and input_check["status"] == "PASS"
                and live_check["status"] == "PASS"
                else "FAIL",
                "blockers": receipt_check["blockers"]
                + isolation_check["blockers"]
                + input_check["blockers"]
                + live_check["blockers"],
                "isolation_receipt": isolation_ref,
                "kernel_receipt": kernel_ref,
                "approved_context_sha256": approved_context_hash,
                "receipt_integrity": receipt_check,
                "saved_isolation": isolation_check,
                "approved_inputs": input_check,
                "live_isolation": live_check,
            }
            save(preflight_path, preflight)
            if preflight["status"] != "PASS":
                raise SystemExit("Q2 preflight failed; historical model call was not started")

            provider._pit_approved = gate
            provider._attempt_journal = journal
            provider.settings.update(
                transport_policy=POLICY,
                isolation_hash=POLICY_HASH,
                isolation_receipt_path=isolation_ref["path"],
                isolation_receipt_sha256=isolation_ref["sha256"],
                kernel_receipt_path=kernel_ref["path"],
                kernel_receipt_sha256=kernel_ref["sha256"],
                activation=activation,
                sandbox_contract_version="CodexPITSandboxV2",
                quarter_package_version=PACKAGE_VERSION,
                policy_version=POLICY_VERSION,
                prompt_version=PROMPT_VERSION,
                schema_version=SCHEMA_VERSION,
                model_identity_confidence="requested_only",
            )
            save(context_path, context)
            journal.emit(
                "stage_completed",
                stage="package_preparation",
                status="completed",
                quarter="FY2023-Q2",
                package_hash=context["quarter_package_manifest"]["package_hash"],
            )
            previous_run_id = db.scalar(
                select(func.max(AIAnalysisRun.id)).where(
                    AIAnalysisRun.model_provider == "codex_cli",
                    AIAnalysisRun.quarter == "FY2023-Q2",
                )
            ) or 0
            before = preservation_hashes(db)
            journal.emit("stage_completed", stage="preservation_before", status="completed")
            snapshot = execute_after_preflight(
                preflight,
                lambda: analyze_approved_context(
                    db,
                    quant,
                    provider,
                    settings.qve_raw_dir,
                    context,
                    approved_context_hash,
                ),
            )
            db.commit()
            run = (
                db.get(AIAnalysisRun, snapshot.analysis_run_id)
                if snapshot is not None
                else db.scalar(
                    select(AIAnalysisRun)
                    .where(
                        AIAnalysisRun.model_provider == "codex_cli",
                        AIAnalysisRun.quarter == "FY2023-Q2",
                        AIAnalysisRun.id > previous_run_id,
                    )
                    .order_by(AIAnalysisRun.id.desc())
                )
            )
            after = preservation_hashes(db)
            preservation_ok = before == after
            save(
                preservation_path,
                {
                    "before": before,
                    "after": after,
                    "all_unchanged": preservation_ok,
                    "tables": [model.__tablename__ for model in TABLES],
                },
            )
            journal.emit(
                "stage_completed",
                stage="preservation_after",
                status="passed" if preservation_ok else "failed",
            )
            if run is None:
                raise SystemExit("The analysis did not persist a run receipt")
            calls = list(
                db.scalars(select(AIProviderCall).where(AIProviderCall.analysis_run_id == run.id))
            )
            rejected = list(
                db.scalars(
                    select(AIUnsupportedClaim).where(AIUnsupportedClaim.analysis_run_id == run.id)
                )
            )
            features = list(
                db.scalars(
                    select(AIAnalystFeature).where(AIAnalystFeature.analysis_run_id == run.id)
                )
            )
            challenges = list(
                db.scalars(select(AIChallenge).where(AIChallenge.analysis_run_id == run.id))
            )
            evidence = list(db.scalars(select(AIEvidence).where(AIEvidence.analysis_run_id == run.id)))
            assessment = assess_single_quarter(
                run, snapshot, calls, evidence, features, challenges, rejected
            )
            if not preservation_ok:
                assessment["blockers"] = sorted(
                    set(assessment["blockers"] + ["quant_or_regime_preservation_changed"])
                )
                assessment["gate"] = "FAIL"
            receipt = {
                **assessment,
                "quarter": "FY2023-Q2",
                "analysis_run_id": run.id,
                "snapshot_id": snapshot.id if snapshot else None,
                "context_hash": approved_context_hash,
                "provider": "codex_cli",
                "requested_model": MODEL,
                "actual_model_identity": "requested_only",
                "transport_policy": POLICY,
                "transport_policy_hash": POLICY_HASH,
                "sandbox_contract_version": "CodexPITSandboxV2",
                "quarter_package_version": PACKAGE_VERSION,
                "policy_version": POLICY_VERSION,
                "prompt_version": PROMPT_VERSION,
                "schema_version": SCHEMA_VERSION,
                "isolation_receipt": isolation_ref,
                "kernel_receipt": kernel_ref,
                "preflight_receipt": str(preflight_path),
                "preflight_sha256": hashlib.sha256(preflight_path.read_bytes()).hexdigest(),
                "calls": len(calls),
                "valid_calls": sum(call.status == "valid" for call in calls),
                "rejected_claim_count": len(rejected),
                "rejection_counts": dict(sorted(Counter(row.reason for row in rejected).items())),
                "call_statuses": [
                    {
                        "id": call.id,
                        "stage": call.stage,
                        "status": call.status,
                        "failure_kind": call.raw_output.get("execution_metadata", {}).get(
                            "failure_kind"
                        ),
                        "package_hash": call.raw_output.get("execution_metadata", {}).get(
                            "quarter_package_hash"
                        ),
                    }
                    for call in calls
                ],
                "preservation_receipt": str(preservation_path),
                "attempt_id": journal.attempt_id,
                "attempt_dir": str(journal.path),
            }
            save(receipt_path, receipt)
            journal.emit(
                "stage_completed",
                stage="q2_assessment",
                status=assessment["gate"].lower(),
                blocker_count=len(assessment["blockers"]),
                analysis_run_id=run.id,
            )
            outcome = "completed" if assessment["gate"] == "PASS" else "failed"
            print(json.dumps(receipt, sort_keys=True))
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        journal.finish(
            status="unknown" if journal.process_state_unknown else outcome,
            failure_kind="termination_unconfirmed" if journal.process_state_unknown else None,
            error_type=error_type,
        )


if __name__ == "__main__":
    main()
