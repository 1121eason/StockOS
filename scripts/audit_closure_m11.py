"""Read-only audit of repeated closure runs and preserved original records."""

import hashlib
import json
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "data/m11-closure"


def read(path):
    return json.loads((out / path).read_text())


def save(path, value):
    (out / path).write_text(json.dumps(value, indent=2, default=str) + "\n")


first, second = (read(f"{name}/counts.json") for name in ("report", "report-second"))
assert first == second, "Offline closure replay changed table counts"
save(
    "idempotency.json",
    dict(
        kind="offline_closure_replay",
        counts_unchanged=True,
        first_counts=first,
        second_counts=second,
    ),
)
quarters = read("report/quarterly-coverage.json")
used = {i for q in quarters for i in q["financial_and_valuation_fact_ids"]}
with sqlite3.connect(f"file:{root / 'data/qve.db'}?mode=ro", uri=True) as db:
    db.row_factory = sqlite3.Row
    conflicts = [
        dict(row)
        for row in db.execute(
            "SELECT id,right_fact_id,status,metadata_json FROM reconciliation_results "
            "WHERE status NOT IN ('match','split_equivalent')"
        )
        if json.loads(row["metadata_json"]).get("version") == "reconciliation-1.1-closure"
    ]
    for row in conflicts:
        meta = json.loads(row.pop("metadata_json"))
        row.update(metric=meta["metric"], period_end=meta["period_end"])
    affected = [r for r in conflicts if r["right_fact_id"] in used]
    save(
        "report/reconciliation-impact.json",
        {
            "scope": [q["quarter"] for q in quarters],
            "scope_includes": "All current-quarter financial facts and all valuation inputs including TTM and carried balances",
            "unresolved_pair_count": len(conflicts),
            "unresolved_pairs": conflicts,
            "affected_candidates": affected,
            "none_selected": not affected,
            "interpretation": "Scoped exclusion only; does not resolve source differences, approve unknown bases, or establish accounting restatements",
        },
    )
    original_path = out / "pre-closure-qve.db"
    if original_path.exists():
        with sqlite3.connect(f"file:{original_path}?mode=ro", uri=True) as original:
            audit = {}
            names = [
                row[0]
                for row in original.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
                )
            ]
            for name in names:
                safe = '"' + name.replace('"', '""') + '"'
                old_rows = [tuple(r) for r in original.execute(f"SELECT * FROM {safe} ORDER BY id")]
                current = {r["id"]: tuple(r) for r in db.execute(f"SELECT * FROM {safe}")}
                columns = [r[1] for r in original.execute(f"PRAGMA table_info({safe})")]
                old_id_index = columns.index("id")
                # Existing schemas may have gained columns; compare every original column by name.
                unchanged = all(
                    tuple(
                        db.execute(
                            f"SELECT {','.join(columns)} FROM {safe} WHERE id=?", (r[old_id_index],)
                        ).fetchone()
                        or ()
                    )
                    == r
                    for r in old_rows
                )
                assert unchanged, f"Original records changed in {name}"
                audit[name] = {
                    "old_rows": len(old_rows),
                    "all_old_rows_unchanged": unchanged,
                    "new_rows": len(current) - len(old_rows),
                    "original_rows_sha256": hashlib.sha256(
                        json.dumps(old_rows, default=str).encode()
                    ).hexdigest(),
                }
            save("preservation-audit.json", audit)
print("Closure counts stable; unresolved candidate usage:", len(affected))
