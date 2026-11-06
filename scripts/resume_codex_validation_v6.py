"""Resume a terminal V6 batch after independently revalidating its passed prefix."""
import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import run_codex_validation_v6 as base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from valuation_engine.ai.attempt_journal import AttemptJournal, workspace_fingerprint
from valuation_engine.config import Settings
from valuation_engine.db.session import engine

PLAN_VERSION = "CodexCohortResumePlanV1"
BUDGET_VERSION = "CodexStageBudgetV2"


def byte_reference(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "error_type": None}


def read_bound(ref):
    actual, value = base.reference(ref["path"])
    if actual != ref:
        raise ValueError("Referenced receipt bytes or normalized path changed")
    return value


def checkpoint(previous_ref, refs):
    """Accept only the completed PASS prefix before the first failed quarter."""
    previous = read_bound(previous_ref)
    if (previous.get("gate") != "FAIL" or previous.get("process_state_unknown") is not False
            or previous.get("inherited_results") or previous.get("required_quarters") != 7):
        raise ValueError("Expected one confirmed terminal original V6 batch")
    origin = Path(previous_ref["path"]).parent
    progress_ref = byte_reference(origin / "progress.jsonl")
    events = [json.loads(line) for line in Path(progress_ref["path"]).read_text().splitlines()]
    if (not events or events[-1].get("event") != "finished" or events[-1].get("status") != "failed"
            or events[-1].get("attempt_id") != previous.get("attempt_id")
            or origin.name != previous.get("attempt_id")):
        raise ValueError("Previous batch has no matching terminal process evidence")
    for name in ("pilot", "isolation", "kernel"):
        if previous.get("references", {}).get(name) != refs[name]:
            raise ValueError("Previous batch changed the pilot or isolation contract")
    original_ref = previous["references"]["plan"]
    original = read_bound(original_ref)
    base.validate_plan(original, refs["pilot"])
    rows = previous.get("results", [])
    if (not rows or len(rows) > 6
            or [row.get("quarter") for row in rows] != original["quarters"][:len(rows)]
            or rows[-1].get("gate") != "FAIL"
            or any(row.get("gate") != "PASS" for row in rows[:-1])
            or previous.get("completed_quarters") != len(rows)):
        raise ValueError("Previous results are not a contiguous PASS prefix followed by FAIL")
    bound = {**refs, "previous_validation": previous_ref,
             "previous_progress": progress_ref, "original_plan": original_ref}
    for i, row in enumerate(rows):
        result_ref, saved = base.reference(origin / "quarters" / row["quarter"] / "result.json")
        if saved != row or row.get("references") != previous["references"]:
            raise ValueError("Previous result receipt mismatch")
        bound[f"previous_result_{i}"] = result_ref
    return original, rows[:-1], bound


def verify_inherited(db, row, expected, refs, directory):
    context_ref, context = base.reference(directory / "context.json")
    preflight_ref, preflight = base.reference(directory / "preflight.json")
    if (row.get("model_started") is not True or row.get("preservation_unchanged") is not True
            or row.get("preflight_sha256") != preflight_ref["sha256"]
            or preflight.get("status") != "PASS"
            or preflight.get("approved_context_sha256") != row.get("context_hash")
            or preflight.get("references") != row["references"]
            or base.context_identity(context) != expected
            or base.digest(context) != row.get("context_hash")):
        raise ValueError("Inherited input or preflight mismatch")
    rows = base.run_rows(db, row["analysis_run_id"])
    result = base.assess_run(rows, row["quarter"], row["context_hash"], refs["isolation"], refs["kernel"])
    if (result["gate"] != "PASS" or any(row.get(k) != v for k, v in result.items())
            or rows["snapshot"] is None or rows["snapshot"].id != row.get("snapshot_id")
            or len(rows["calls"]) != row.get("calls")
            or sum(c.status == "valid" for c in rows["calls"]) != row.get("valid_calls")
            or rows["snapshot"].metadata_json.get("missing_features", []) != row.get("missing_features")):
        raise ValueError("Inherited receipt does not match independently assessed database rows")
    legacy = base.execution_budget("CodexStageBudgetV1")
    for call in rows["calls"]:
        meta = call.raw_output.get("execution_metadata", {})
        if (meta.get("stage_timeout_seconds") != legacy["stage_seconds"].get(call.stage)
                or meta.get("timeout_seconds") != 180 or meta.get("max_attempts") != 2
                or meta.get("execution_budget", legacy) != legacy):
            raise ValueError("Inherited execution budget does not match the declared legacy profile")
    return context_ref, preflight_ref


def prepare_resume_plan(db, settings, previous_ref, refs):
    pilot = read_bound(refs["pilot"])
    isolation, kernel = read_bound(refs["isolation"]), read_bound(refs["kernel"])
    base.verify_pilot(db, pilot, refs["isolation"], refs["kernel"])
    if base.gates.verify_saved_isolation(refs["isolation"], isolation, refs["kernel"], kernel)["status"] != "PASS":
        raise ValueError("Saved isolation failed")
    original, passed, bound = checkpoint(previous_ref, refs)
    fresh = base.prepare_plan(db, settings, refs["pilot"])
    if fresh != original:
        raise ValueError("Frozen source, context, package or contract changed")
    origin = Path(previous_ref["path"]).parent
    carried = []
    for i, row in enumerate(passed):
        context_ref, preflight_ref = verify_inherited(
            db, row, fresh["inputs"][row["quarter"]], refs, origin / "quarters" / row["quarter"]
        )
        bound[f"inherited_context_{i}"] = context_ref
        bound[f"inherited_preflight_{i}"] = preflight_ref
        carried.append({"quarter": row["quarter"], "analysis_run_id": row["analysis_run_id"],
                        "snapshot_id": row["snapshot_id"], "receipt": bound[f"previous_result_{i}"],
                        "execution_budget": base.execution_budget("CodexStageBudgetV1")})
    return {"version": PLAN_VERSION, "contract": base.contract(), "references": bound,
            "execution_budget": base.execution_budget(BUDGET_VERSION), "inherited_results": carried,
            "quarters": fresh["quarters"][len(passed):], "inputs": fresh["inputs"],
            "repeatability": "NOT_RUN", "human_reviews": "NOT_RUN"}


def require_exact_plan(plan, expected):
    if plan != expected:
        raise ValueError("Resume plan differs from the freshly revalidated checkpoint")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pilot-receipt", "isolation-receipt", "kernel-receipt", "previous-validation"):
        parser.add_argument("--" + name, type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-plan", type=Path, help="Read-only revalidation; no CLI or inference")
    mode.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    args = parser.parse_args(argv)
    if args.plan and not base.gates._is_sha256(args.plan_sha256):
        parser.error("Execution requires the exact --plan-sha256")
    refs = {name: base.reference(getattr(args, name + "_receipt"))[0]
            for name in ("pilot", "isolation", "kernel")}
    previous_ref, _ = base.reference(args.previous_validation)
    settings = Settings()
    if not settings.qve_database_url.startswith("sqlite:///"):
        raise ValueError("Formal resume currently requires the verified SQLite checkout")
    dbpath = Path(settings.qve_database_url.removeprefix("sqlite:///")).resolve()
    readonly = create_engine("sqlite://", creator=lambda: sqlite3.connect(dbpath.as_uri() + "?mode=ro", uri=True))
    try:
        with Session(readonly) as db:
            expected = prepare_resume_plan(db, settings, previous_ref, refs)
    finally:
        readonly.dispose()
    if args.prepare_plan:
        base.gates.save(args.prepare_plan, expected)
        print(json.dumps({"plan": byte_reference(args.prepare_plan), "quarters": expected["quarters"],
                          "inherited_results": expected["inherited_results"]}))
        return 0
    plan_ref, plan = base.reference(args.plan)
    if plan_ref["sha256"] != args.plan_sha256:
        raise ValueError("Resume plan bytes hash mismatch")
    require_exact_plan(plan, expected)
    refs = {**plan["references"], "plan": plan_ref}
    isolation, kernel = read_bound(refs["isolation"]), read_bound(refs["kernel"])
    journal = AttemptJournal(base.gates.OUT / "attempts", purpose="codex_pit_resume_v6_budget_v2",
                             manifest={"git": workspace_fingerprint(Path.cwd()), "references": refs,
                                       "contract": base.contract(), "execution_budget": plan["execution_budget"]})
    results = []
    outcome = "failed"
    error_type = None
    try:
        journal.emit("runner_started", stage="cohort_resume", status="started", pid=os.getpid())
        with Session(engine(settings.qve_database_url)) as db:
            require_exact_plan(plan, prepare_resume_plan(db, settings, previous_ref,
                                                        {k: refs[k] for k in ("pilot", "isolation", "kernel")}))

            def record(current):
                results[:] = current
                base.gates.save(journal.path / f"progress-{len(current):02d}.json", {"results": current})

            base.execute_quarters(plan, lambda quarter: base.run_quarter(
                db, settings, quarter, plan["inputs"][quarter], refs, isolation, kernel, journal,
                budget_version=BUDGET_VERSION,
            ), record)
        if len(results) == len(plan["quarters"]) and all(row["gate"] == "PASS" for row in results):
            outcome = "completed"
        return 0 if outcome == "completed" else 1
    except BaseException as exc:
        error_type = type(exc).__name__
        raise
    finally:
        base.gates.save(journal.path / "validation.json", {
            "gate": "PASS" if outcome == "completed" else "FAIL", "results": results,
            "inherited_results": plan["inherited_results"], "execution_budget": plan["execution_budget"],
            "completed_quarters": 1 + len(plan["inherited_results"]) + sum(r["gate"] == "PASS" for r in results),
            "required_quarters": 7, "references": refs, "attempt_id": journal.attempt_id,
            "error_type": error_type, "process_state_unknown": journal.process_state_unknown,
            "repeatability": "NOT_RUN", "human_reviews": "NOT_RUN", "m4_1_final_pass": False,
        })
        journal.finish(status="unknown" if journal.process_state_unknown else outcome,
                       failure_kind="termination_unconfirmed" if journal.process_state_unknown else None,
                       error_type=error_type)


if __name__ == "__main__":
    raise SystemExit(main())
