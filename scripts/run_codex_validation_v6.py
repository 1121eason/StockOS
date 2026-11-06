"""Execute the six approved V6 quarters sequentially against a byte-pinned input plan."""

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import get_args

import run_codex_pilot_v5 as gates
from run_codex_validation_v5 import run_rows
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from valuation_engine.ai.attempt_journal import AttemptJournal, workspace_fingerprint
from valuation_engine.ai.cli_provider import CodexCLIProvider
from valuation_engine.ai.contracts import FeatureName
from valuation_engine.ai.guards import safe_narrative
from valuation_engine.ai.pilot import assess_single_quarter
from valuation_engine.ai.quarter_package import build_package
from valuation_engine.ai.service import prepare
from valuation_engine.ai.validation import QUARTERS
from valuation_engine.config import Settings
from valuation_engine.db.schema import AIAnalysisRun
from valuation_engine.db.session import engine
from valuation_engine.db.store import digest
from valuation_engine.quant.ai_context import resolve_run

PLAN_VERSION = "CodexCohortPlanV6"
PROMPT = "PromptSetV6"
COUNTERS = (
    "external_network_success", "external_file_success", "external_connector_success",
    "external_future_fact_received", "permission_escalation_requested", "permission_escalation_granted",
)


def execution_budget(version):
    """Named finite limits; semantic input and extraction batching stay unchanged."""
    if version not in {"CodexStageBudgetV1", "CodexStageBudgetV2"}:
        raise ValueError("Unknown execution budget version")
    seconds = 180 if version == "CodexStageBudgetV1" else 600
    return {"version": version, "provider_timeout_seconds": seconds,
            "stage_seconds": {"extract": seconds, "synthesize": 600, "challenge": 600},
            "max_attempts": 2, "chunk_characters": 18000}


def verify_execution_budget(rows, budget):
    expected = {"execution_budget": budget, "timeout_seconds": budget["provider_timeout_seconds"],
                "max_attempts": budget["max_attempts"]}
    if not rows.get("run") or not rows.get("calls"):
        return ["execution_budget_mismatch"]
    if any(rows["run"].settings_json.get(k) != v for k, v in expected.items()):
        return ["execution_budget_mismatch"]
    for call in rows["calls"]:
        meta = call.raw_output.get("execution_metadata", {})
        if (call.stage not in budget["stage_seconds"]
                or meta.get("stage_timeout_seconds") != budget["stage_seconds"].get(call.stage)
                or type(meta.get("retry_count")) is not int
                or not 0 <= meta["retry_count"] < budget["max_attempts"]
                or any(meta.get(k) != v for k, v in expected.items())):
            return ["execution_budget_mismatch"]
    return []


def contract():
    if gates.PROMPT_VERSION != PROMPT:
        raise ValueError("V6 requires the pinned prompt version")
    return {
        "provider": "codex_cli", "requested_model": gates.MODEL,
        "prompt_version": PROMPT, "policy_version": gates.POLICY_VERSION,
        "schema_version": gates.SCHEMA_VERSION, "cli_version": gates.VERSION,
        "transport_policy_hash": gates.POLICY_HASH, "package_version": gates.PACKAGE_VERSION,
    }


def reference(path):
    ref, value = gates.read_explicit_receipt(path)
    if ref["error_type"] is not None:
        raise ValueError("Unreadable explicit JSON reference")
    return ref, value


def context_identity(context):
    package = build_package(context)["manifest"]
    if package != context.get("quarter_package_manifest"):
        raise ValueError("Prepared package manifest mismatch")
    quant = context["quant_context"]
    return {
        "context_hash": digest(context), "forecast_run_id": quant["forecast_run_id"],
        "quarter": quant["quarter"], "information_cutoff": quant["information_cutoff"],
        "source_document_ids": gates.normalize_source_ids([
            doc["source_document_id"] for doc in context["sources"]["documents"]
        ]), "package": package,
    }


def assess_run(rows, quarter, expected_context_hash, isolation_ref, kernel_ref):
    """Recompute the existing quarter gate and verify persisted transport bindings."""
    run = rows["run"]
    if run is None:
        return {"gate": "FAIL", "blockers": ["analysis_run_missing"]}
    result = assess_single_quarter(
        run, rows["snapshot"], rows["calls"], rows["evidence"], rows["features"],
        rows["challenges"], rows["rejected"], expected_quarter=quarter,
    )
    blockers = list(result["blockers"])
    if (run.model_provider != "codex_cli" or run.model_name != gates.MODEL
            or run.prompt_version != PROMPT or run.policy_version != gates.POLICY_VERSION
            or run.schema_version != gates.SCHEMA_VERSION
            or digest(run.context_json) != expected_context_hash):
        blockers.append("run_contract_or_context_mismatch")
    evidence = {item.evidence_key: item for item in rows["evidence"]}
    for feature in rows["features"]:
        if any(key not in evidence or evidence[key].topic != feature.feature_name
               for key in feature.metadata_json.get("evidence_keys", [])):
            blockers.append("admitted_feature_topic_mismatch")
    narratives = [f.rationale for f in rows["features"]] + [c.description for c in rows["challenges"]]
    if rows["snapshot"]:
        narratives += [s["summary"] for s in rows["snapshot"].metadata_json.get("sections", {}).values()]
    if not all(safe_narrative(value) for value in narratives):
        blockers.append("unsafe_formal_narrative")
    for call in rows["calls"]:
        raw = call.raw_output
        meta = raw.get("execution_metadata", {})
        response = raw.get("raw_response", {})
        if call.request_hash != digest([call.stage, call.exact_prompt]) or call.response_hash != digest(raw):
            blockers.append("call_hash_mismatch")
        if (meta.get("cli_version") != gates.VERSION
                or meta.get("quarter_package_hash") != result["package_hash"]
                or meta.get("exit_code") != 0 or meta.get("failure_kind") is not None
                or response.get("process_state") != "confirmed_stopped"
                or response.get("turn_completed") is not True
                or response.get("first_failure") is not None
                or response.get("runner_termination_requests") != []
                or any(response.get(name) != 0 for name in COUNTERS)):
            blockers.append("call_lifecycle_or_isolation_failed")
        for name, ref in (("isolation", isolation_ref), ("kernel", kernel_ref)):
            if (meta.get(name + "_receipt_path") != ref["path"]
                    or meta.get(name + "_receipt_sha256") != ref["sha256"]):
                blockers.append("call_receipt_binding_mismatch")
        if call.stage == "synthesize":
            payload = call.exact_prompt["untrusted_data"]
            index = {name: [] for name in get_args(FeatureName)}
            for item in payload["evidence"]:
                index.setdefault(item["topic"], []).append(item["key"])
            if payload.get("feature_evidence_keys") != {name: sorted(keys) for name, keys in index.items()}:
                blockers.append("synthesis_index_mismatch")
    return {**result, "gate": "FAIL" if blockers else "PASS", "blockers": sorted(set(blockers))}


def verify_pilot(db, pilot, isolation_ref, kernel_ref):
    for key, expected in contract().items():
        pilot_key = "quarter_package_version" if key == "package_version" else key
        if key != "cli_version" and pilot.get(pilot_key) != expected:
            raise ValueError("Pilot contract mismatch: " + key)
    if pilot.get("gate") != "PASS" or pilot.get("quarter") != QUARTERS[0]:
        raise ValueError("A passing Q2 pilot is required")
    if pilot.get("isolation_receipt") != isolation_ref or pilot.get("kernel_receipt") != kernel_ref:
        raise ValueError("Pilot isolation/kernel reference mismatch")
    rows = run_rows(db, pilot["analysis_run_id"])
    if rows["run"] is None or rows["snapshot"] is None:
        raise ValueError("Pilot database rows are missing")
    if rows["snapshot"].id != pilot.get("snapshot_id"):
        raise ValueError("Pilot snapshot mismatch")
    if gates.verify_q2_inputs(rows["run"].context_json, expected_prompt_version=PROMPT)["status"] != "PASS":
        raise ValueError("Pilot fixed Q2 inputs changed")
    assessment = assess_run(rows, QUARTERS[0], pilot.get("context_hash"), isolation_ref, kernel_ref)
    if assessment["gate"] != "PASS" or any(pilot.get(k) != v for k, v in assessment.items()):
        raise ValueError("Pilot receipt does not match database assessment")
    preflight_ref, preflight = reference(pilot["preflight_receipt"])
    if (preflight_ref["sha256"] != pilot["preflight_sha256"]
            or preflight.get("status") != "PASS"
            or preflight.get("approved_context_sha256") != pilot["context_hash"]):
        raise ValueError("Pilot preflight binding mismatch")
    progress = Path(pilot["attempt_dir"]) / "progress.jsonl"
    terminal = json.loads(progress.read_text().splitlines()[-1])
    if terminal.get("event") != "finished" or terminal.get("status") != "completed":
        raise ValueError("Pilot attempt is not confirmed completed")
    return assessment


def validate_plan(plan, pilot_ref):
    if (plan.get("version") != PLAN_VERSION or plan.get("contract") != contract()
            or plan.get("quarters") != list(QUARTERS[1:])
            or plan.get("pilot_receipt") != pilot_ref
            or set(plan.get("inputs", {})) != set(QUARTERS[1:])):
        raise ValueError("Cohort plan contract/order/pilot mismatch")
    for quarter in QUARTERS[1:]:
        if plan["inputs"][quarter].get("quarter") != quarter:
            raise ValueError("Cohort plan quarter identity mismatch")


def prepare_plan(db, settings, pilot_ref):
    inputs = {}
    for quarter in QUARTERS[1:]:
        quant = resolve_run(db, 1, quarter)
        inputs[quarter] = context_identity(prepare(db, quant, settings.qve_raw_dir))
    return {
        "version": PLAN_VERSION, "contract": contract(), "quarters": list(QUARTERS[1:]),
        "pilot_receipt": pilot_ref, "inputs": inputs,
    }


def execute_quarters(plan, execute, record):
    """Never dispatch a later quarter after a failed or unknown predecessor."""
    results = []
    for quarter in plan["quarters"]:
        row = execute(quarter)
        results.append(row)
        record(results)
        if row.get("gate") != "PASS":
            break
    return results


def run_quarter(db, settings, quarter, expected, refs, gate, kernel, journal,
                *, budget_version="CodexStageBudgetV1"):
    budget = execution_budget(budget_version)
    directory = journal.path / "quarters" / quarter
    if journal.process_state_unknown:
        row = {"quarter": quarter, "gate": "FAIL", "blockers": ["termination_unconfirmed"], "model_started": False}
        gates.save(directory / "result.json", row)
        return row
    quant = resolve_run(db, 1, quarter)
    context = prepare(db, quant, settings.qve_raw_dir)
    observed = context_identity(context)
    # Verify static inputs before even performing CLI discovery.
    saved = gates.verify_saved_isolation(refs["isolation"], gate, refs["kernel"], kernel)
    inputs_ok = observed == expected
    checks = {
        "saved_isolation": saved,
        "inputs": {"status": "PASS" if inputs_ok else "FAIL", "expected": expected, "actual": observed},
        "receipts": gates.receipt_references_unchanged(*refs.values(), gate["discovery_receipt"]),
    }
    if inputs_ok and saved["status"] == "PASS" and checks["receipts"]["status"] == "PASS":
        provider = CodexCLIProvider(gates.MODEL, timeout=budget["provider_timeout_seconds"])
        capability = provider.check()
        gates.save(directory / "provider-check.json", capability)
        checks["live_isolation"] = gates.verify_live_isolation(
            capability, gate, gates.current_user_config_hash()
        )
        # Re-read receipt bytes after discovery, immediately before inference.
        checks["receipts"] = gates.receipt_references_unchanged(*refs.values(), gate["discovery_receipt"])
    else:
        checks["live_isolation"] = {"status": "NOT_RUN"}
    blockers = [name + "_failed" for name, check in checks.items() if check["status"] != "PASS"]
    preflight = {
        "status": "FAIL" if blockers else "PASS", "blockers": blockers, "checks": checks,
        "quarter": quarter, "approved_context_sha256": observed["context_hash"], "references": refs,
        "execution_budget": budget,
    }
    gates.save(directory / "context.json", context)
    gates.save(directory / "preflight.json", preflight)
    journal.emit("stage_completed", stage="quarter_preflight", status=preflight["status"].lower(), quarter=quarter)
    if blockers:
        row = {"quarter": quarter, "gate": "FAIL", "blockers": blockers, "model_started": False}
        gates.save(directory / "result.json", row)
        return row
    provider._pit_approved = gate
    provider._attempt_journal = journal
    provider.settings.update(
        transport_policy=gates.POLICY, isolation_hash=gates.POLICY_HASH,
        isolation_receipt_path=refs["isolation"]["path"], isolation_receipt_sha256=refs["isolation"]["sha256"],
        kernel_receipt_path=refs["kernel"]["path"], kernel_receipt_sha256=refs["kernel"]["sha256"],
        activation="six_quarter_validation_v6", sandbox_contract_version="CodexPITSandboxV2",
        quarter_package_version=gates.PACKAGE_VERSION, policy_version=gates.POLICY_VERSION,
        prompt_version=PROMPT, schema_version=gates.SCHEMA_VERSION, model_identity_confidence="requested_only",
        execution_budget=budget,
    )
    before = gates.preservation_hashes(db)
    previous = db.scalar(select(func.max(AIAnalysisRun.id))) or 0
    snapshot = gates.execute_after_preflight(preflight, lambda: gates.analyze_approved_context(
        db, quant, provider, settings.qve_raw_dir, context, observed["context_hash"]
    ))
    db.commit()
    run_id = snapshot.analysis_run_id if snapshot else db.scalar(
        select(AIAnalysisRun.id).where(
            AIAnalysisRun.id > previous, AIAnalysisRun.model_provider == "codex_cli",
            AIAnalysisRun.quarter == quarter,
        ).order_by(AIAnalysisRun.id.desc())
    )
    after = gates.preservation_hashes(db)
    preserved = before == after
    gates.save(directory / "preservation.json", {"before": before, "after": after, "all_unchanged": preserved})
    if run_id is None:
        assessment = {"gate": "FAIL", "blockers": ["analysis_run_missing"]}
        rows = None
    else:
        rows = run_rows(db, run_id)
        assessment = assess_run(rows, quarter, observed["context_hash"], refs["isolation"], refs["kernel"])
    additional = []
    if budget_version == "CodexStageBudgetV2" and rows is not None:
        additional += verify_execution_budget(rows, budget)
    if not preserved:
        additional.append("quant_or_regime_preservation_changed")
    if run_id is not None and run_id <= previous:
        additional.append("fresh_analysis_run_required")
    if journal.process_state_unknown:
        additional.append("termination_unconfirmed")
    if gates.receipt_references_unchanged(*refs.values(), gate["discovery_receipt"])["status"] != "PASS":
        additional.append("receipt_changed_during_execution")
    if gates.current_user_config_hash() != gate["configuration_hash_before"]:
        additional.append("configuration_changed_during_execution")
    if additional:
        assessment = {**assessment, "gate": "FAIL", "blockers": sorted(set(assessment["blockers"] + additional))}
    row = {
        **assessment, "quarter": quarter, "analysis_run_id": run_id,
        "snapshot_id": snapshot.id if snapshot else None, "model_started": True,
        "context_hash": observed["context_hash"], "preservation_unchanged": preserved,
        "references": refs, "preflight_sha256": hashlib.sha256((directory / "preflight.json").read_bytes()).hexdigest(),
        "calls": len(rows["calls"]) if rows else 0,
        "valid_calls": sum(call.status == "valid" for call in rows["calls"]) if rows else 0,
        "missing_features": snapshot.metadata_json.get("missing_features", []) if snapshot else None,
        "execution_budget": budget,
        "rejection_counts": dict(Counter(x.reason for x in rows["rejected"])) if rows else {},
    }
    gates.save(directory / "result.json", row)
    journal.emit("stage_completed", stage="quarter_validation", status=row["gate"].lower(),
                 quarter=quarter, analysis_run_id=run_id, feature_count=row.get("feature_count"), blockers=row["blockers"])
    print(json.dumps({"quarter": quarter, "gate": row["gate"], "run_id": run_id, "blockers": row["blockers"]}), flush=True)
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-receipt", type=Path, required=True)
    parser.add_argument("--isolation-receipt", type=Path, required=True)
    parser.add_argument("--kernel-receipt", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-plan", type=Path, help="Read-only input preparation; no CLI or model calls")
    mode.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    args = parser.parse_args(argv)
    if args.plan and not gates._is_sha256(args.plan_sha256):
        parser.error("Execution requires the exact --plan-sha256")
    refs = {}
    refs["pilot"], pilot = reference(args.pilot_receipt)
    refs["isolation"], gate = reference(args.isolation_receipt)
    refs["kernel"], kernel = reference(args.kernel_receipt)
    settings = Settings()
    # Plan preparation and all pilot checks use an explicitly read-only database connection.
    url = settings.qve_database_url
    if not url.startswith("sqlite:///"):
        raise ValueError("Formal cohort execution currently requires the verified SQLite checkout")
    import sqlite3

    from sqlalchemy import create_engine

    dbpath = Path(url.removeprefix("sqlite:///")).resolve()
    readonly = create_engine("sqlite://", creator=lambda: sqlite3.connect(dbpath.as_uri() + "?mode=ro", uri=True))
    with Session(readonly) as db:
        verify_pilot(db, pilot, refs["isolation"], refs["kernel"])
        saved = gates.verify_saved_isolation(refs["isolation"], gate, refs["kernel"], kernel)
        if saved["status"] != "PASS":
            raise ValueError("Saved isolation failed")
        if args.prepare_plan:
            plan = prepare_plan(db, settings, refs["pilot"])
            gates.save(args.prepare_plan, plan)
            print(json.dumps({"plan": str(args.prepare_plan.resolve()), "sha256": hashlib.sha256(args.prepare_plan.read_bytes()).hexdigest(), "quarters": plan["quarters"]}))
    readonly.dispose()
    if args.prepare_plan:
        return 0
    refs["plan"], plan = reference(args.plan)
    if refs["plan"]["sha256"] != args.plan_sha256:
        raise ValueError("Plan bytes hash mismatch")
    validate_plan(plan, refs["pilot"])
    journal = AttemptJournal(gates.OUT / "attempts", purpose="codex_pit_six_quarter_validation_v6",
                             manifest={"git": workspace_fingerprint(Path.cwd()), "references": refs, "contract": contract()})
    results = []
    outcome = "failed"
    error_type = None
    try:
        journal.emit("runner_started", stage="cohort", status="started", pid=os.getpid())
        with Session(engine(settings.qve_database_url)) as db:
            verify_pilot(db, pilot, refs["isolation"], refs["kernel"])

            def record(current):
                results[:] = current
                gates.write_immutable_json(journal.path / f"progress-{len(current):02d}.json", current)

            execute_quarters(plan, lambda quarter: run_quarter(
                db, settings, quarter, plan["inputs"][quarter], refs, gate, kernel, journal
            ), record)
        if len(results) == 6 and all(row["gate"] == "PASS" for row in results):
            outcome = "completed"
        return 0 if outcome == "completed" else 1
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        final = {
            "gate": "PASS" if outcome == "completed" else "FAIL", "results": results,
            "completed_quarters": 1 + sum(row["gate"] == "PASS" for row in results),
            "required_quarters": 7, "pilot_receipt": refs["pilot"], "references": refs,
            "attempt_id": journal.attempt_id, "error_type": error_type,
            "process_state_unknown": journal.process_state_unknown,
            "repeatability": "NOT_RUN", "human_reviews": "NOT_RUN", "m4_1_final_pass": False,
        }
        gates.save(journal.path / "validation.json", final)
        journal.finish(status="unknown" if journal.process_state_unknown else outcome,
                       failure_kind="termination_unconfirmed" if journal.process_state_unknown else None,
                       error_type=error_type)


if __name__ == "__main__":
    raise SystemExit(main())
