"""One explicit FY2023-Q2 rerun using the PITQuarterPackageV1 contract."""

import json
from collections import Counter
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from valuation_engine.ai.cli_provider import CodexCLIProvider
from valuation_engine.ai.codex_pit import MODEL, POLICY, POLICY_HASH
from valuation_engine.ai.contracts import POLICY_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from valuation_engine.ai.pilot import assess_single_quarter
from valuation_engine.ai.quarter_package import VERSION as PACKAGE_VERSION
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
RECEIPT = OUT / "pilot-v3.json"
CONTEXT = OUT / "FY2023-Q2-context-v3.json"
PRESERVATION = OUT / "preservation-v3.json"
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
        result[model.__tablename__] = {
            "count": len(rows),
            "content_hash": digest(rows),
        }
    return result


def main():
    if RECEIPT.exists():
        raise SystemExit("pilot-v3 receipt exists; reruns require a new explicit receipt version")
    gate_path = OUT / "experiment-v3.json"
    gate = json.loads(gate_path.read_text())
    if gate.get("gate") != "PASS" or gate.get("policy_hash") != POLICY_HASH:
        raise SystemExit("The persisted Codex PIT isolation gate does not match this transport policy")
    if not gate.get("gates") or not all(value == "PASS" for value in gate["gates"].values()):
        raise SystemExit("Every saved Codex PIT isolation gate must pass before historical input")
    settings = Settings()
    provider = CodexCLIProvider(MODEL, timeout=180)
    capability = provider.check()
    save(OUT / "pilot-v3-provider-check.json", capability)
    if capability.get("reason") != "PIT_PROBES_REQUIRED":
        raise SystemExit("Codex discovery/auth/configuration check did not pass")
    provider._pit_approved = gate
    provider.settings.update(
        transport_policy=POLICY,
        isolation_hash=POLICY_HASH,
        activation="single_quarter_pilot_v3",
        sandbox_contract_version="CodexPITSandboxV2",
        quarter_package_version=PACKAGE_VERSION,
        policy_version=POLICY_VERSION,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        model_identity_confidence="requested_only",
    )
    with Session(engine(settings.qve_database_url)) as db:
        quant = resolve_run(db, 1, "FY2023-Q2")
        context = prepare(db, quant, settings.qve_raw_dir)
        save(CONTEXT, context)
        previous_run_id = db.scalar(
            select(func.max(AIAnalysisRun.id)).where(
                AIAnalysisRun.model_provider == "codex_cli",
                AIAnalysisRun.quarter == "FY2023-Q2",
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
                    AIAnalysisRun.quarter == "FY2023-Q2",
                    AIAnalysisRun.id > previous_run_id,
                )
                .order_by(AIAnalysisRun.id.desc())
            )
        )
        after = preservation_hashes(db)
        preservation_ok = before == after
        save(
            PRESERVATION,
            {
                "before": before,
                "after": after,
                "all_unchanged": preservation_ok,
                "tables": [model.__tablename__ for model in TABLES],
            },
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
            "context_hash": digest(context),
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
            "preservation_receipt": str(PRESERVATION),
        }
        save(RECEIPT, receipt)
        print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
