"""Audit preserved M1.1 data, backend numerical parity, solver residuals and nullable coverage."""

import hashlib
import json
import sqlite3
from pathlib import Path

from sqlalchemy.orm import Session

from valuation_engine.db.schema import ForecastRun, ResearchValuation
from valuation_engine.db.session import engine
from valuation_engine.research.forecast import FIELDS, actual_period, fcff_proxy
from valuation_engine.research.inputs import FinancialInputs
from valuation_engine.research.numbers import D, canonical, p

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/m2"


def load(path):
    return json.loads((OUT / path).read_text())


def save(path, value):
    (OUT / path).write_text(json.dumps(canonical(value), indent=2, sort_keys=True) + "\n")


def main():
    preservation = {}
    for name in ("qve", "labels"):
        with (
            sqlite3.connect(OUT / f"pre-m2-{name}.db") as old,
            sqlite3.connect(f"file:{ROOT}/data/{name}.db?mode=ro", uri=True, timeout=60) as current,
        ):
            for (table,) in old.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%' and name!='alembic_version'"
            ):
                columns = [r[1] for r in old.execute(f'pragma table_info("{table}")')]
                idx = columns.index("id")
                rows = list(old.execute(f'select * from "{table}" order by id'))
                unchanged = all(
                    tuple(
                        current.execute(
                            f'select {",".join(columns)} from "{table}" where id=?', (r[idx],)
                        ).fetchone()
                        or ()
                    )
                    == r
                    for r in rows
                )
                assert unchanged, (name, table)
                preservation[name + ":" + table] = dict(
                    original_rows=len(rows),
                    all_original_rows_unchanged=unchanged,
                    original_content_sha256=hashlib.sha256(
                        json.dumps(rows, default=str).encode()
                    ).hexdigest(),
                )
    save("preservation.json", preservation)
    freeze = load("policy-freeze.json")
    assert all(
        hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == h
        for path, h in freeze["files"].items()
    )
    sqlite_history, pg_history = load("report/history.json"), load("postgresql/history.json")

    def key(row):
        return row["quarter"], row["checkpoint"], row["model"]

    other = {key(r): r for r in pg_history["runs"]}
    differences = []
    compared = 0
    for row in sqlite_history["runs"]:
        peer = other[key(row)]
        for left, right in zip(row["periods"], peer["periods"], strict=True):
            for field in FIELDS:
                compared += 1
                if left[field] != right[field]:
                    differences.append(
                        [key(row), left["period_type"], field, left[field], right[field]]
                    )
    solver = []
    readiness = []
    with (
        Session(engine("sqlite:///data/qve.db")) as sql,
        Session(engine("postgresql+psycopg://postgres@127.0.0.1:55439/qve_verified")) as pg,
    ):
        for row in sqlite_history["runs"]:
            if row["checkpoint"] != "first_tradable":
                continue
            left = sql.get(ResearchValuation, row["valuation_id"])
            right = pg.get(ResearchValuation, other[key(row)]["valuation_id"])
            for column in ResearchValuation.__table__.columns:
                if column.name in (
                    "id",
                    "identity_key",
                    "company_id",
                    "forecast_run_id",
                    "source_valuation_id",
                    "as_of_timestamp",
                    "valuation_model_version",
                    "metadata_json",
                    "created_at",
                ):
                    continue
                a, b = getattr(left, column.name), getattr(right, column.name)
                compared += 1
                if a != b:
                    differences.append([key(row), "valuation", column.name, str(a), str(b)])
            reverse = left.metadata_json["reverse_dcf"]
            if reverse["status"] == "converged":
                ratio = abs(D(reverse["residual"])) / D(reverse["current_ev"])
                assert ratio <= p("reverse_relative_tolerance")
                solver.append(
                    dict(
                        quarter=row["quarter"],
                        model=row["model"],
                        valuation_id=left.id,
                        relative_residual_exact=str(ratio),
                        within_tolerance=True,
                    )
                )
            if row["model"] != "Guidance Anchored Baseline":
                continue
            run = sql.get(ForecastRun, row["run_id"])
            data = FinancialInputs(sql, 1, run.information_cutoff)
            components = []
            for q in data.history[:4]:
                actual = actual_period(data, q)
                proxy = fcff_proxy(actual)
                components.append(
                    dict(
                        quarter=f"FY{q.fiscal_year}-Q{q.fiscal_quarter}" if q else None,
                        actual_tax_rate=actual["tax_rate"] if actual else None,
                        fcff_proxy=proxy,
                        reason="eligible"
                        if proxy is not None
                        else "missing_components_or_historical_effective_tax_rate_outside_0_1",
                        fact_ids=sorted({i for o in q.metrics.values() for i in o.fact_ids})
                        if q
                        else [],
                    )
                )
            readiness.append(
                dict(
                    quarter=row["quarter"],
                    forecast_run_id=run.id,
                    starting_fcff=run.metadata_json["starting_fcff"],
                    enterprise_value=left.metadata_json["enterprise_value"],
                    reverse_status=reverse,
                    components=components,
                    policy="V1 does not normalize historical abnormal effective tax rates or manufacture missing inputs",
                )
            )
    save(
        "backend-parity.json",
        dict(
            all_numeric_outputs_equal=not differences,
            numeric_cells_compared=compared,
            differences=differences,
            policy_freeze_verified=True,
        ),
    )
    assert not differences, differences[:5]
    save("report/solver-audit.json", solver)
    save("report/reverse-input-readiness.json", readiness)
    # Preserve completeness statuses; add a separate PIT verdict instead of treating null as a value.
    for folder in ("report", "postgresql"):
        gates = load(f"{folder}/gates.json")
        for g in gates:
            g["pit_status"] = (
                "PASS"
                if all(
                    v
                    for k, v in g["checks"].items()
                    if k
                    not in (
                        "q1_income_complete",
                        "forward_valuation_available",
                        "dcf_available",
                        "reverse_dcf_converged",
                    )
                )
                else "FAIL"
            )
        save(f"{folder}/gates.json", gates)
    print(
        "Preservation and numerical parity passed:", compared, "cells; solver checks:", len(solver)
    )


if __name__ == "__main__":
    main()
