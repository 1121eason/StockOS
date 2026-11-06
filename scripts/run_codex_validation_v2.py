"""Execute the remaining approved Codex cohort only after the Q2 V2 pilot passes."""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from valuation_engine.ai.cli_provider import CodexCLIProvider
from valuation_engine.ai.codex_pit import MODEL, POLICY, POLICY_HASH
from valuation_engine.ai.pilot import assess_single_quarter
from valuation_engine.ai.quarter_package import VERSION as PACKAGE_VERSION
from valuation_engine.ai.service import analyze, prepare
from valuation_engine.ai.validation import QUARTERS, compare, export_review, review_status
from valuation_engine.config import Settings
from valuation_engine.db.schema import (
    AIAnalysisRun,
    AIAnalystFeature,
    AIAnalystSnapshot,
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
RUN_DIR = OUT / "validation-v2"
PROGRESS = RUN_DIR / "progress.json"
RECEIPT = OUT / "validation-v2.json"
REPEAT_RECEIPT = RUN_DIR / "repeatability.json"
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


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    temporary.replace(path)


def preservation_hashes(db):
    result = {}
    for model in TABLES:
        rows = [
            {column.name: getattr(row, column.key) for column in model.__table__.columns}
            for row in db.scalars(select(model).order_by(model.id))
        ]
        result[model.__tablename__] = {"count": len(rows), "content_hash": digest(rows)}
    return result


def run_rows(db, run_id):
    return {
        "run": db.get(AIAnalysisRun, run_id),
        "snapshot": db.scalar(
            select(AIAnalystSnapshot).where(AIAnalystSnapshot.analysis_run_id == run_id)
        ),
        "calls": list(
            db.scalars(select(AIProviderCall).where(AIProviderCall.analysis_run_id == run_id))
        ),
        "evidence": list(
            db.scalars(select(AIEvidence).where(AIEvidence.analysis_run_id == run_id))
        ),
        "features": list(
            db.scalars(select(AIAnalystFeature).where(AIAnalystFeature.analysis_run_id == run_id))
        ),
        "challenges": list(
            db.scalars(select(AIChallenge).where(AIChallenge.analysis_run_id == run_id))
        ),
        "rejected": list(
            db.scalars(
                select(AIUnsupportedClaim).where(AIUnsupportedClaim.analysis_run_id == run_id)
            )
        ),
    }


def main():
    if PROGRESS.exists() or RECEIPT.exists():
        raise SystemExit("Codex validation V2 has a saved run; no implicit rerun or resume")
    pilot = json.loads((OUT / "pilot-v2.json").read_text())
    gate_receipt = json.loads((OUT / "experiment-v3.json").read_text())
    if (
        pilot.get("gate") != "PASS"
        or pilot.get("quarter") != QUARTERS[0]
        or pilot.get("transport_policy_hash") != POLICY_HASH
        or gate_receipt.get("gate") != "PASS"
        or gate_receipt.get("policy_hash") != POLICY_HASH
        or not all(value == "PASS" for value in gate_receipt["gates"].values())
    ):
        raise SystemExit("FY2023-Q2 and Codex isolation gates must both pass before cohort expansion")
    settings = Settings()
    provider = CodexCLIProvider(MODEL, timeout=180)
    capability = provider.check()
    save(RUN_DIR / "provider-check.json", capability)
    if capability.get("reason") != "PIT_PROBES_REQUIRED":
        raise SystemExit("Codex discovery/auth/configuration check did not pass")
    provider._pit_approved = gate_receipt
    provider.settings.update(
        transport_policy=POLICY,
        isolation_hash=POLICY_HASH,
        activation="single_quarter_pilot_v2",
        sandbox_contract_version="CodexPITSandboxV2",
        quarter_package_version=PACKAGE_VERSION,
        policy_version=pilot["policy_version"],
        prompt_version=pilot["prompt_version"],
        schema_version=pilot["schema_version"],
        model_identity_confidence="requested_only",
    )
    results: list[dict[str, Any]] = [
        {
            "quarter": QUARTERS[0],
            "analysis_run_id": pilot["analysis_run_id"],
            "snapshot_id": pilot["snapshot_id"],
            "gate": "PASS",
            "source": "pilot-v2.json",
        }
    ]
    progress = {"provider": "codex_cli", "model": MODEL, "results": results, "halted_at": None}
    save(PROGRESS, progress)
    halted = None
    with Session(engine(settings.qve_database_url)) as db:
        for quarter in QUARTERS[1:]:
            quant = resolve_run(db, 1, quarter)
            context = prepare(db, quant, settings.qve_raw_dir)
            save(RUN_DIR / f"{quarter}-context.json", context)
            previous_run_id = db.scalar(
                select(func.max(AIAnalysisRun.id)).where(
                    AIAnalysisRun.model_provider == "codex_cli",
                    AIAnalysisRun.quarter == quarter,
                )
            ) or 0
            before = preservation_hashes(db)
            snapshot = analyze(db, quant, provider, settings.qve_raw_dir, refresh=True)
            db.commit()
            run = (
                db.get(AIAnalysisRun, snapshot.analysis_run_id)
                if snapshot is not None
                else db.scalar(
                    select(AIAnalysisRun)
                    .where(
                        AIAnalysisRun.model_provider == "codex_cli",
                        AIAnalysisRun.quarter == quarter,
                        AIAnalysisRun.id > previous_run_id,
                    )
                    .order_by(AIAnalysisRun.id.desc())
                )
            )
            if run is None:
                assessment = {"gate": "FAIL", "blockers": ["analysis_run_missing"]}
                row = {"quarter": quarter, **assessment}
            else:
                rows = run_rows(db, run.id)
                assessment = assess_single_quarter(
                    rows["run"],
                    rows["snapshot"],
                    rows["calls"],
                    rows["evidence"],
                    rows["features"],
                    rows["challenges"],
                    rows["rejected"],
                    expected_quarter=quarter,
                )
                after = preservation_hashes(db)
                preserved = before == after
                if not preserved:
                    assessment["blockers"] = sorted(
                        set(assessment["blockers"] + ["quant_or_regime_preservation_changed"])
                    )
                    assessment["gate"] = "FAIL"
                row = {
                    "quarter": quarter,
                    "analysis_run_id": run.id,
                    "snapshot_id": rows["snapshot"].id if rows["snapshot"] else None,
                    **assessment,
                    "preservation_unchanged": preserved,
                }
            results.append(row)
            progress["results"] = results
            progress["halted_at"] = quarter if row["gate"] != "PASS" else None
            save(PROGRESS, progress)
            if row["gate"] != "PASS":
                halted = quarter
                break

        all_seven = len(results) == 7 and all(row["gate"] == "PASS" for row in results)
        repeats = []
        if all_seven:
            targets = {QUARTERS[0]: pilot["analysis_run_id"], QUARTERS[1]: results[1]["analysis_run_id"]}
            for quarter in QUARTERS[:2]:
                original_id = targets[quarter]
                original = db.get(AIAnalysisRun, original_id)
                quant = resolve_run(db, 1, quarter)
                context = prepare(db, quant, settings.qve_raw_dir)
                if digest(original.context_json) != digest(context):
                    repeats.append({"quarter": quarter, "gate": "FAIL", "reason": "context_changed"})
                    continue
                before = preservation_hashes(db)
                repeated = analyze(db, quant, provider, settings.qve_raw_dir, refresh=True)
                db.commit()
                if repeated is None:
                    repeats.append({"quarter": quarter, "gate": "FAIL", "reason": "fresh_rerun_failed"})
                    continue
                repeat_rows = run_rows(db, repeated.analysis_run_id)
                acceptance = assess_single_quarter(
                    repeat_rows["run"],
                    repeated,
                    repeat_rows["calls"],
                    repeat_rows["evidence"],
                    repeat_rows["features"],
                    repeat_rows["challenges"],
                    repeat_rows["rejected"],
                    expected_quarter=quarter,
                )
                after = preservation_hashes(db)
                metrics = compare(db, original_id, repeated.analysis_run_id)
                same_inputs = all(
                    metrics[key]
                    for key in (
                        "same_provider",
                        "same_context",
                        "same_prompt_version",
                        "same_schema_version",
                        "same_exact_prompt_hashes",
                        "same_package_hash",
                        "same_requested_model",
                        "same_cli_version",
                    )
                )
                fresh = repeated.analysis_run_id != original_id
                preserved = before == after
                status = (
                    "PASS"
                    if acceptance["gate"] == "PASS" and same_inputs and fresh and preserved
                    else "FAIL"
                )
                repeats.append(
                    {
                        "quarter": quarter,
                        "gate": status,
                        "fresh_run_id": repeated.analysis_run_id,
                        "original_run_id": original_id,
                        "same_inputs": same_inputs,
                        "fresh_rerun": fresh,
                        "preservation_unchanged": preserved,
                        "acceptance": acceptance,
                        "comparison": metrics,
                    }
                )
            save(REPEAT_RECEIPT, repeats)
        if all_seven:
            export_review(db, RUN_DIR / "human-review", "codex_cli", MODEL)
        human = review_status(db, "codex_cli", MODEL)

    repeat_ok = len(repeats) == 2 and all(row.get("gate") == "PASS" for row in repeats)
    final = {
        "gate": "PASS" if all_seven else "FAIL",
        "halted_at": halted,
        "completed_quarters": sum(row["gate"] == "PASS" for row in results),
        "required_quarters": 7,
        "results": results,
        "repeatability_gate": "PASS" if repeat_ok else "INCOMPLETE_OR_FAIL",
        "repeatability": repeats,
        "human_review": {
            "required": human["required"],
            "completed": human["completed"],
            "pending": len(human["pending"]),
            "human_gate_complete": human["human_gate_complete"],
            "cards": str(RUN_DIR / "human-review/human-review-cards.generated.json")
            if all_seven
            else None,
        },
        "m4_1_final_pass": bool(all_seven and repeat_ok and human["human_gate_complete"]),
        "m5_authorized": False,
    }
    save(RECEIPT, final)
    print(json.dumps(final, sort_keys=True))


if __name__ == "__main__":
    main()
