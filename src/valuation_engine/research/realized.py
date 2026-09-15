"""PIT realized financial aggregates; no label-store dependency."""

from valuation_engine.research.forecast import actual_period, aggregate
from valuation_engine.research.inputs import period_tuple


def realized_period(data, predicted):
    kind = predicted["period_type"]
    targets = (
        [(predicted["fiscal_year"], predicted["fiscal_quarter"])]
        if kind == "quarter"
        else [period_tuple(c["period"]) for c in predicted["metadata_json"]["components"]]
    )
    if not targets or any(t > data.anchor for t in targets):
        return None, None, []
    quarters = [data.quarter(*t) for t in targets]
    if any(q is None or q.value("revenue") is None for q in quarters):
        return None, None, []
    actuals = [actual_period(data, q) for q in quarters]
    actual = actuals[0] if kind == "quarter" else aggregate(actuals, kind, predicted["fiscal_year"])
    availability = max(o.available_at for q in quarters for o in q.metrics.values())
    ids = sorted({i for q in quarters for o in q.metrics.values() for i in o.fact_ids})
    return actual, availability, ids
