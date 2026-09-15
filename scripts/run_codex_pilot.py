"""Exactly one historical pilot after persisted synthetic gate PASS."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from valuation_engine.ai.cli_provider import CodexCLIProvider
from valuation_engine.ai.codex_pit import MODEL, POLICY, POLICY_HASH
from valuation_engine.ai.service import analyze, prepare
from valuation_engine.config import Settings
from valuation_engine.db.schema import (
    AIAnalysisRun,
    AIAnalystFeature,
    AIChallenge,
    AIEvidence,
    AIProviderCall,
    AIUnsupportedClaim,
)
from valuation_engine.db.session import engine
from valuation_engine.db.store import digest
from valuation_engine.quant.ai_context import resolve_run

OUT = Path("data/m41/codex")


def main():
    if (OUT / "pilot.json").exists():
        raise SystemExit("Pilot receipt already exists; no implicit retry")
    gate = json.loads((OUT / "experiment.json").read_text())
    assert gate["gate"] == "PASS" and gate["policy_hash"] == POLICY_HASH
    settings = Settings()
    provider = CodexCLIProvider(MODEL, "/Users/eason/.local/bin/codex", 180)
    status = provider.check()
    assert status["authenticated"] and status["reason"] == "PIT_PROBES_REQUIRED"
    provider._pit_approved = gate
    provider.settings.update(
        transport_policy=POLICY,
        isolation_hash=POLICY_HASH,
        activation="single_pilot",
        model_identity_confidence="requested_only",
    )
    with Session(engine(settings.qve_database_url)) as db:
        quant = resolve_run(db, 1, "FY2023-Q2")
        context = prepare(db, quant, settings.qve_raw_dir)
        (OUT / "FY2023-Q2-context.json").write_text(json.dumps(context, default=str, indent=2))
        result = analyze(db, quant, provider, settings.qve_raw_dir)
        db.commit()
        run = db.scalar(
            select(AIAnalysisRun)
            .where(AIAnalysisRun.model_provider == "codex_cli")
            .order_by(AIAnalysisRun.id.desc())
        )
        calls = list(
            db.scalars(select(AIProviderCall).where(AIProviderCall.analysis_run_id == run.id))
        )
        rejected = list(
            db.scalars(
                select(AIUnsupportedClaim).where(AIUnsupportedClaim.analysis_run_id == run.id)
            )
        )
        features = list(
            db.scalars(select(AIAnalystFeature).where(AIAnalystFeature.analysis_run_id == run.id))
        )
        challenges = list(
            db.scalars(select(AIChallenge).where(AIChallenge.analysis_run_id == run.id))
        )
        evidence = list(db.scalars(select(AIEvidence).where(AIEvidence.analysis_run_id == run.id)))
        kinds = {c.kind for c in challenges}
        clean_calls = bool(calls) and all(
            c.status == "valid"
            and not c.raw_output.get("execution_metadata", {}).get("failure_kind")
            for c in calls
        )
        # No retry or seven-quarter promotion on incomplete, rejected or unsupported output.
        passes = (
            bool(result)
            and clean_calls
            and not rejected
            and bool(features)
            and {"upside", "downside", "regime"} <= kinds
        )
        receipt = {
            "quarter": "FY2023-Q2",
            "analysis_run_id": run.id,
            "snapshot_id": result.id if result else None,
            "gate": "PASS" if passes else "FAIL",
            "context_hash": digest(context),
            "calls": len(calls),
            "valid_calls": sum(c.status == "valid" for c in calls),
            "evidence": len(evidence),
            "features": len(features),
            "challenges": len(challenges),
            "challenge_kinds": sorted(kinds),
            "rejected_claims": len(rejected),
            "rejection_reasons": [x.reason for x in rejected],
            "policy_hash": POLICY_HASH,
            "calls_status": [
                {
                    "id": c.id,
                    "stage": c.stage,
                    "status": c.status,
                    "failure": c.raw_output.get("execution_metadata", {}).get("failure_kind"),
                }
                for c in calls
            ],
        }
        (OUT / "pilot.json").write_text(json.dumps(receipt, indent=2))
        print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
