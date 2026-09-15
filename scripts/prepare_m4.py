"""Prepare the 26 PIT research contexts; never substitute fixture AI for a missing provider."""

import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy.orm import Session

from valuation_engine.ai.service import analyze, prepare
from valuation_engine.cli.ai import provider
from valuation_engine.cli.main import migrate
from valuation_engine.config import Settings
from valuation_engine.db.session import engine
from valuation_engine.regime.features import eligible_runs
from valuation_engine.research.numbers import canonical
from valuation_engine.time import now

REPRESENTATIVE = (
    "FY2023-Q2",
    "FY2023-Q3",
    "FY2024-Q1",
    "FY2024-Q2",
    "FY2025-Q4",
    "FY2026-Q1",
    "FY2027-Q2",
)
REVIEW = REPRESENTATIVE[:5]
CATEGORIES = (
    "demand",
    "supply",
    "competition",
    "product_cycle",
    "management",
    "anomalies",
    "model_challenge",
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--all-quarters", action="store_true")
    parser.add_argument("--out", default="data/m4/report")
    args = parser.parse_args()
    settings = Settings()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    migrate(settings)
    model = provider(settings) if args.execute else None
    manifests = []
    with Session(engine(settings.qve_database_url)) as db:
        runs = eligible_runs(db, 1, now())
        ordered = sorted(
            runs, key=lambda r: (r.metadata_json["anchor"] not in REPRESENTATIVE, r.forecast_as_of)
        )
        for run in ordered:
            quarter = run.metadata_json["anchor"]
            if model and args.all_quarters and quarter not in REPRESENTATIVE:
                if not all(
                    r["analysis_status"] == "completed"
                    for r in manifests
                    if r["quarter"] in REPRESENTATIVE
                ):
                    raise RuntimeError(
                        "Representative quarters must complete before full-history execution"
                    )
            prepared = prepare(db, run, settings.qve_raw_dir)
            (out / f"{quarter}-context.json").write_text(
                json.dumps(canonical(prepared), indent=2, sort_keys=True) + "\n"
            )
            result = {
                "quarter": quarter,
                "as_of": run.forecast_as_of.isoformat(),
                "source_coverage": prepared["sources"]["coverage"],
                "sources": prepared["sources"]["documents"],
                "context_sha256": hashlib.sha256(
                    (out / f"{quarter}-context.json").read_bytes()
                ).hexdigest(),
                "analysis_status": "not_executed",
                "analysis_run_id": None,
                "snapshot_id": None,
            }
            if model and (args.all_quarters or quarter in REPRESENTATIVE):
                snapshot = analyze(db, run, model, settings.qve_raw_dir)
                db.commit()
                result.update(
                    analysis_status="completed" if snapshot else "failed_or_missing_source",
                    analysis_run_id=snapshot.analysis_run_id if snapshot else None,
                    snapshot_id=snapshot.id if snapshot else None,
                )
            manifests.append(result)
            print(
                quarter,
                result["source_coverage"]["narrative_blocks"],
                result["analysis_status"],
                flush=True,
            )
        (out / "coverage.json").write_text(json.dumps(manifests, indent=2, sort_keys=True) + "\n")
        review = [
            {
                "quarter": r["quarter"],
                "analysis_run_id": r["analysis_run_id"],
                "category": category,
                "verdict": None,
                "reviewer": None,
                "notes": None,
                "evidence_ids": [],
                "review_status": "pending_actual_ai_output_and_human_review",
            }
            for r in manifests
            if r["quarter"] in REVIEW
            for category in CATEGORIES
        ]
        review_path = out / "human-review-set.json"
        if review_path.exists() and any(
            x.get("verdict") for x in json.loads(review_path.read_text())
        ):
            review_path = out / "human-review-template.json"
        review_path.write_text(json.dumps(review, indent=2) + "\n")
        print("Prepared", len(manifests), "quarters; human review not fabricated.")


if __name__ == "__main__":
    main()
