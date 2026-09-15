"""Replay the frozen financial regime policy and report stability and sensitivity."""

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from valuation_engine.cli.main import migrate
from valuation_engine.config import Settings
from valuation_engine.db.schema import Base, ResearchValuation, SourceDocument
from valuation_engine.db.session import engine
from valuation_engine.db.store import read_document
from valuation_engine.regime.confidence import (
    POLICY,
    snapshot_contract,
)
from valuation_engine.regime.confidence import (
    classify_corrected as classify,
)
from valuation_engine.regime.policy import REGIMES, sensitivity_policies
from valuation_engine.regime.service import replay, transitions
from valuation_engine.research.numbers import D, canonical, dispersion, mean

ROOT = Path(__file__).resolve().parents[1]


def save(out, name, value):
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.json").write_text(json.dumps(canonical(value), indent=2, sort_keys=True) + "\n")


def counts(db):
    return {
        name: db.scalar(select(func.count()).select_from(table))
        for name, table in Base.metadata.tables.items()
    }


def stability(states):
    labels = [s["primary_regime"] for s in states]
    changes = sum(a != b for a, b in zip(labels, labels[1:], strict=False))
    flips = sum(a == c and a != b for a, b, c in zip(labels, labels[1:], labels[2:], strict=False))
    durations = []
    for i, label in enumerate(labels):
        if i == 0 or label != labels[i - 1]:
            durations.append(1)
        else:
            durations[-1] += 1
    probability_changes = [
        abs(D(b["probabilities"][r]) - D(a["probabilities"][r]))
        for a, b in zip(states, states[1:], strict=False)
        for r in REGIMES
    ]
    cycle_changes = [
        D(b["cycle_score"]) - D(a["cycle_score"])
        for a, b in zip(states, states[1:], strict=False)
        if a["cycle_score"] is not None and b["cycle_score"] is not None
    ]
    return {
        "snapshot_count": len(states),
        "regime_changes": changes,
        "change_frequency": D(changes) / (len(states) - 1) if len(states) > 1 else None,
        "one_quarter_flips": flips,
        "one_quarter_flip_frequency": D(flips) / (len(states) - 2) if len(states) > 2 else None,
        "regime_durations_quarters": durations,
        "average_observed_regime_duration": mean(durations),
        "duration_note": "First and last segments are boundary-censored; observed length only",
        "mean_absolute_probability_change": mean(probability_changes),
        "cycle_change_dispersion": dispersion(cycle_changes),
    }


def preserve(out):
    report = {}
    for name in ("qve", "labels"):
        with (
            sqlite3.connect(ROOT / f"data/m31/pre-m31-{name}.db") as old,
            sqlite3.connect(ROOT / f"data/{name}.db") as new,
        ):
            for (table,) in old.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            ):
                columns = [r[1] for r in old.execute(f'PRAGMA table_info("{table}")')]
                rows = list(old.execute(f'SELECT * FROM "{table}" ORDER BY id'))
                idx = columns.index("id")
                equal = all(
                    tuple(
                        new.execute(
                            f'SELECT {",".join(columns)} FROM "{table}" WHERE id=?', (r[idx],)
                        ).fetchone()
                        or ()
                    )
                    == r
                    for r in rows
                )
                assert equal, (name, table)
                report[f"{name}:{table}"] = {
                    "original_rows": len(rows),
                    "all_original_rows_unchanged": equal,
                }
    save(out, "preservation", report)


def run(settings, out, through, audit_originals=True):
    if settings.qve_database_url == "sqlite:///data/qve.db" and audit_originals:
        if not all((ROOT / f"data/m31/pre-m31-{name}.db").is_file() for name in ("qve", "labels")):
            raise ValueError(
                "Original-row audit needs pre-M3 backups. For a delivered bundle, verify its preservation receipt and use --skip-preservation-audit; replay and hash checks still run."
            )
    freeze = json.loads((ROOT / "data/m31/policy-freeze.json").read_text())
    assert all(
        hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
        for path, digest in freeze["files"].items()
    )
    migrate(settings)
    with Session(engine(settings.qve_database_url)) as db:
        before = counts(db)
        records, states, packs = replay(db, 1, through, POLICY)
        events = transitions(db, [r.id for r in records])
        db.commit()
        first = counts(db)
        repeated, states2, _ = replay(db, 1, through, POLICY)
        db.commit()
        after = counts(db)
        assert [r.id for r in repeated] == [r.id for r in records]
        assert states == states2 and first == after
        scenarios = []
        for name, policy in sensitivity_policies(POLICY):
            alternative = []
            for pack in packs:
                alternative.append(classify(pack, alternative, policy))
            fraction = D(
                sum(
                    a["primary_regime"] != b["primary_regime"]
                    for a, b in zip(states, alternative, strict=True)
                )
            ) / len(states)
            scenarios.append(
                {
                    "name": name,
                    "policy": policy,
                    "changed_label_fraction": fraction,
                    "within_prespecified_tolerance": fraction
                    <= D(POLICY["sensitivity_max_label_change_fraction"]),
                    "mean_absolute_probability_difference": mean(
                        [
                            abs(D(a["probabilities"][r]) - D(b["probabilities"][r]))
                            for a, b in zip(states, alternative, strict=True)
                            for r in REGIMES
                        ]
                    ),
                    "mean_absolute_cycle_difference": mean(
                        [
                            abs(D(a["cycle_score"]) - D(b["cycle_score"]))
                            for a, b in zip(states, alternative, strict=True)
                            if a["cycle_score"] is not None and b["cycle_score"] is not None
                        ]
                    ),
                    "stability": stability(alternative),
                    "states": alternative,
                }
            )
        # The optional combined view begins AFTER classification; never passed to policy/replay.
        combined = []
        for record, state, pack in zip(records, states, packs, strict=True):
            valuation = db.scalar(
                select(ResearchValuation).where(
                    ResearchValuation.forecast_run_id == record.forecast_run_id
                )
            )
            if valuation:
                assert valuation.as_of_timestamp <= record.as_of_timestamp
            combined.append(
                {
                    "quarter": state["quarter"],
                    "regime": state["primary_regime"],
                    "candidate": state["candidate_regime"],
                    "cycle_score": state["cycle_score"],
                    "eps_revision": pack["features"]["eps_revision"],
                    **{
                        k: getattr(valuation, k) if valuation else None
                        for k in (
                            "ntm_pe",
                            "forward_fcf_yield",
                            "dcf_base",
                            "reverse_dcf_implied_fcf_cagr",
                        )
                    },
                }
            )
        sources = list(db.scalars(select(SourceDocument)))
        for source in sources:
            assert hashlib.sha256(read_document(source)).hexdigest() == source.content_hash
        save(
            out,
            "history",
            {
                "states": states,
                "snapshot_ids": [r.id for r in records],
                "inputs": packs,
                "contracts": [snapshot_contract(r) for r in records],
            },
        )
        save(out, "transitions", events)
        save(out, "stability", stability(states))
        save(out, "sensitivity", scenarios)
        save(out, "combined", combined)
        save(
            out,
            "idempotency",
            {
                "before": before,
                "first": first,
                "repeat": after,
                "all_counts_unchanged": first == after,
                "all_states_identical": states == states2,
            },
        )
        summary = {
            "quarters": len(states),
            "first_quarter": states[0]["quarter"],
            "last_quarter": states[-1]["quarter"],
            "regime_counts": {r: sum(s["primary_regime"] == r for s in states) for r in REGIMES},
            "transition_count": len(events),
            "all_source_hashes_verified": True,
            "source_count": len(sources),
            "sensitivity_all_within_tolerance": all(
                s["within_prespecified_tolerance"] for s in scenarios
            ),
            "policy_freeze_verified": True,
        }
        save(out, "summary", summary)
        print(json.dumps(summary, indent=2))
    if settings.qve_database_url == "sqlite:///data/qve.db" and audit_originals:
        preserve(out)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/m31/report")
    parser.add_argument("--as-of", default="2026-09-12T00:00:00+00:00")
    parser.add_argument(
        "--skip-preservation-audit",
        action="store_true",
        help="Bundled replay only: retain the supplied original-row audit receipt; do not re-audit absent backups",
    )
    args = parser.parse_args()
    run(
        Settings(),
        Path(args.out),
        datetime.fromisoformat(args.as_of),
        audit_originals=not args.skip_preservation_audit,
    )
