"""Reproduce M2 research history, financial-only evaluation, gates and idempotency evidence."""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from valuation_engine.cli.main import migrate
from valuation_engine.config import Settings
from valuation_engine.db.schema import (
    Base,
    ForecastRun,
    LabelBase,
    QuarterlySnapshot,
    ResearchValuation,
    SourceDocument,
)
from valuation_engine.db.session import engine
from valuation_engine.db.store import read_document
from valuation_engine.evaluation.forecasts import evaluate
from valuation_engine.research.history import replay
from valuation_engine.research.inputs import FinancialInputs
from valuation_engine.research.numbers import POLICY, D, canonical, dispersion, div, mean
from valuation_engine.research.service import MODELS, stored_periods

REPS = {"FY2022-Q1", "FY2023-Q3", "FY2024-Q1", "FY2025-Q2", "FY2027-Q2"}


def save(out, name, value):
    out.mkdir(parents=True, exist_ok=True)
    (out / (name + ".json")).write_text(
        json.dumps(canonical(value), indent=2, sort_keys=True) + "\n"
    )


def counts(db, labels):
    return {
        **{
            name: db.scalar(select(func.count()).select_from(table))
            for name, table in Base.metadata.tables.items()
        },
        **{
            "labels:" + name: labels.scalar(select(func.count()).select_from(table))
            for name, table in LabelBase.metadata.tables.items()
        },
    }


def forecast_safe(run):
    cutoff = run.information_cutoff

    def parse(x):
        return datetime.fromisoformat(x.replace("Z", "+00:00"))

    m = run.metadata_json
    observations = m["provenance"]["observations"].values()
    return (
        all(parse(o["available_at"]) <= cutoff for o in observations)
        and all(parse(g["available_at"]) <= cutoff for g in m["raw_guidance"].values())
        and all(
            parse(s["actual_available_at"]) <= cutoff
            and parse(s["guidance"]["available_at"]) <= cutoff
            for b in m["guidance_bias"].values()
            for s in b["samples"]
        )
    )


def evidence(db, history):
    rows = []
    gates = []
    stability = []
    for entry in history["runs"]:
        run = db.get(ForecastRun, entry["run_id"])
        if entry["checkpoint"] != "first_tradable" or entry["model"] != MODELS["A"]:
            continue
        value = db.get(ResearchValuation, entry["valuation_id"])
        periods = stored_periods(db, run.id)
        q1 = next(r for r in periods if r["period_type"] == "quarter")
        horizons = {r["period_type"]: r for r in periods if r["period_type"] != "quarter"}
        row = dict(
            quarter=entry["quarter"],
            forecast_run_id=run.id,
            valuation_id=value.id,
            information_cutoff=run.information_cutoff,
            tradable_at=run.tradable_at,
            q1_revenue=q1["revenue"],
            q1_eps=q1["eps"],
            q1_gross_margin=q1["gross_margin"],
            q1_opex=q1["operating_expenses"],
            q1_fcf=q1["free_cash_flow"],
            ntm_revenue=horizons["NTM"]["revenue"],
            ntm_eps=horizons["NTM"]["eps"],
            ntm_fcf=horizons["NTM"]["free_cash_flow"],
            fy1_eps=horizons["FY1"]["eps"],
            fy2_eps=horizons["FY2"]["eps"],
            ntm_pe=value.ntm_pe,
            fy1_pe=value.fy1_pe,
            fy2_pe=value.fy2_pe,
            forward_fcf_yield=value.forward_fcf_yield,
            forward_ev_ebit=value.forward_ev_ebit,
            dcf_base=value.dcf_base,
            dcf_low=value.dcf_low,
            dcf_high=value.dcf_high,
            reverse_dcf_implied_fcf_cagr=value.reverse_dcf_implied_fcf_cagr,
            internal_fcf_cagr=value.internal_fcf_cagr,
            expectations_gap=value.expectations_gap,
            missing=value.metadata_json["missing"],
            forecast_missing={kind: r["metadata_json"]["missing"] for kind, r in horizons.items()},
            q1_interval=q1["metadata_json"]["intervals"],
            warning_count=len(run.metadata_json["warnings"]),
        )
        rows.append(row)
        if entry["quarter"] not in REPS:
            continue
        issuer_entry = next(
            r
            for r in history["runs"]
            if r["quarter"] == entry["quarter"]
            and r["checkpoint"] == "issuer_release"
            and r["model"] == MODELS["A"]
        )
        issuer = db.get(ForecastRun, issuer_entry["run_id"])
        before = FinancialInputs(db, 1, issuer.information_cutoff - timedelta(microseconds=1))
        snapshot = db.get(QuarterlySnapshot, run.input_snapshot_id)
        source = value.metadata_json["source_valuation"]
        shares = source["shares"]
        quote = source["price"]

        def parse(x):
            return datetime.fromisoformat(x.replace("Z", "+00:00"))

        interval_safe = all(
            parse(sample["actual_available_at"]) <= run.information_cutoff
            and parse(sample["origin_as_of"]) < run.information_cutoff
            for period in periods
            for band in period["metadata_json"]["intervals"].values()
            for sample in band["samples"]
        )
        checks = dict(
            before_boundary_does_not_use_new_quarter=f"FY{before.anchor[0]}-Q{before.anchor[1]}"
            != entry["quarter"],
            issuer_inputs_public=forecast_safe(issuer),
            first_tradable_inputs_public=forecast_safe(run),
            intervals_only_realized_history=interval_safe,
            first_permitted_price=quote is not None
            and parse(quote["available_at"]) == run.tradable_at,
            pit_shares=shares is not None
            and parse(shares["available_at"]) <= run.information_cutoff,
            balances_public=all(
                parse(v["available_at"]) <= run.information_cutoff
                for k, v in source["inputs"].items()
                if k.startswith("balance:")
            ),
            historical_context_strict=all(
                parse(t) < run.information_cutoff
                for t in value.metadata_json["context_prior_timestamps"]
            ),
            q1_income_complete=all(
                q1[k] is not None
                for k in (
                    "revenue",
                    "gross_margin",
                    "operating_expenses",
                    "net_income",
                    "eps",
                    "free_cash_flow",
                )
            ),
            forward_valuation_available=value.ntm_pe is not None
            and value.forward_fcf_yield is not None,
            dcf_available=value.dcf_base is not None,
            reverse_dcf_converged=value.metadata_json["reverse_dcf"]["status"] == "converged",
        )
        gates.append(
            dict(
                quarter=entry["quarter"],
                status="PASS" if all(checks.values()) else "PARTIAL",
                pit_status="PASS"
                if all(
                    v
                    for k, v in checks.items()
                    if k
                    not in (
                        "q1_income_complete",
                        "forward_valuation_available",
                        "dcf_available",
                        "reverse_dcf_converged",
                    )
                )
                else "FAIL",
                checks=checks,
                before_anchor=f"FY{before.anchor[0]}-Q{before.anchor[1]}",
                issuer_forecast={c.name: getattr(issuer, c.name) for c in issuer.__table__.columns},
                first_tradable_forecast={
                    c.name: getattr(run, c.name) for c in run.__table__.columns
                },
                known_financial_snapshot=snapshot.payload,
                forecast_periods=periods,
                revision=entry["revision"],
                valuation={c.name: getattr(value, c.name) for c in value.__table__.columns},
            )
        )
    for model in MODELS.values():
        selected = [
            e
            for e in history["runs"]
            if e["checkpoint"] == "first_tradable" and e["model"] == model
        ]
        for metric in ("revenue", "eps", "free_cash_flow"):
            values = [
                next(r for r in e["periods"] if r["period_type"] == "NTM")[metric] for e in selected
            ]
            values = [D(v) if v is not None else None for v in values]
            changes = [
                div(b - a, abs(a))
                for a, b in zip(values[:-1], values[1:], strict=True)
                if a is not None and b is not None and a != 0
            ]
            revision_values = []
            for e in selected:
                for r in e["revision"].get("comparisons", []):
                    if r["new_label"] == "FY1":
                        v = r["metrics"][metric]["percentage_revision"]
                        if v is not None:
                            revision_values.append(D(v))
            stability.append(
                dict(
                    model=model,
                    metric=metric,
                    forecast_volatility=dispersion(changes),
                    revision_volatility=dispersion(revision_values),
                    forecast_change_mean=mean(changes),
                    revision_sample_count=len(revision_values),
                    forecast_failure_frequency=D(sum(v is None for v in values)) / len(values)
                    if values
                    else None,
                    forecast_change_note="Rolling NTM includes window roll; identical-fiscal-target revision volatility is separate. EPS forecast changes must be split-normalized; see adjusted result below.",
                )
            )
            # NTM EPS change is basis-normalized, not a mechanical split discontinuity.
            if metric == "eps":
                adjusted = []
                from datetime import date

                from valuation_engine.hardening.basis import SplitBasis

                split = SplitBasis(db, 1)
                for previous, current, a, b in zip(
                    selected[:-1], selected[1:], values[:-1], values[1:], strict=True
                ):
                    if a is None or b is None or a == 0:
                        continue
                    old_run = db.get(ForecastRun, previous["run_id"])
                    new_run = db.get(ForecastRun, current["run_id"])
                    factor = split.factor(
                        date.fromisoformat(old_run.metadata_json["provenance"]["basis_date"]),
                        date.fromisoformat(new_run.metadata_json["provenance"]["basis_date"]),
                    )
                    normalized = a / factor
                    adjusted.append((b - normalized) / abs(normalized))
                stability[-1].update(
                    forecast_volatility=dispersion(adjusted),
                    forecast_change_mean=mean(adjusted),
                    forecast_change_note="Rolling NTM EPS changes normalized to each new cutoff share basis before comparison.",
                )
    return rows, gates, stability


def run(settings, out, through, repeat=False):
    migrate(settings)
    with (
        Session(engine(settings.qve_database_url)) as db,
        Session(engine(settings.qve_label_database_url)) as labels,
    ):
        history = replay(db, through, progress=lambda q: print("Replayed", q, flush=True))
        save(out, "history", history)
        evaluation = evaluate(db, labels, through)
        labels.commit()
        save(out, "accuracy", evaluation)
        first_counts = counts(db, labels)
        if repeat:
            second = replay(db, through, progress=lambda q: print("Repeated", q, flush=True))
            again = evaluate(db, labels, through)
            labels.commit()
            assert canonical(history) == canonical(second), "Forecast replay changed"
            assert canonical(evaluation) == canonical(again), "Evaluation replay changed"
            assert first_counts == counts(db, labels), "Duplicate rows on second replay"
            save(
                out,
                "idempotency",
                dict(
                    all_counts_unchanged=True,
                    all_forecasts_equal=True,
                    all_evaluations_equal=True,
                    counts=first_counts,
                ),
            )
        rows, gates, stability = evidence(db, history)
        save(out, "coverage", rows)
        save(out, "gates", gates)
        save(out, "stability", stability)
        verified = {
            doc.id: bool(read_document(doc, settings.qve_raw_dir))
            for doc in db.scalars(select(SourceDocument))
        }
        summary = dict(
            model_version=POLICY["version"],
            classification=POLICY["classification"],
            checkpoints=len(history["runs"]),
            quarter_count=len(rows),
            coverage={
                key: sum(row[key] is not None for row in rows)
                for key in (
                    "q1_revenue",
                    "q1_eps",
                    "ntm_eps",
                    "fy1_eps",
                    "fy2_eps",
                    "ntm_pe",
                    "forward_fcf_yield",
                    "dcf_base",
                    "reverse_dcf_implied_fcf_cagr",
                )
            },
            gates={g["quarter"]: g["status"] for g in gates},
            all_source_hashes_verified=all(verified.values()),
            source_hash_count=len(verified),
            counts=counts(db, labels),
            model_failure_frequency={
                model: sum(
                    next(r for r in e["periods"] if r["period_type"] == "NTM")["eps"] is None
                    for e in history["runs"]
                    if e["model"] == model and e["checkpoint"] == "first_tradable"
                )
                for model in MODELS.values()
            },
        )
        save(out, "summary", summary)
        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("data/m2/report"))
    parser.add_argument("--through", default="2026-09-12T00:00:00+00:00")
    parser.add_argument("--repeat", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            canonical(
                run(Settings(), args.output, datetime.fromisoformat(args.through), args.repeat)
            ),
            indent=2,
        )
    )
