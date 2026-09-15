"""Feature-specific PIT observation/quality graph. V1 financial calculations are unchanged."""

from datetime import datetime
from typing import Any

from sqlalchemy import select

from valuation_engine.db.schema import DataQualityIssue, FinancialFact
from valuation_engine.db.store import digest
from valuation_engine.normalization.quarterly import prior_period
from valuation_engine.regime.features import extract
from valuation_engine.research.inputs import period_name, period_tuple
from valuation_engine.research.numbers import D, canonical
from valuation_engine.research.service import stored_periods
from valuation_engine.time import aware

DIAGNOSTICS = {
    "revenue_qoq",
    "operating_leverage",
    "dso",
    "capex_to_revenue",
    "fcf_growth",
    "forecast_error_history",
    "forecast_interval_width",
    "forecast_sample_count",
}


def attach_quality(pack, ledger):
    """Join warnings to exact active observations; retain non-active warnings without penalties."""
    graph = pack["feature_lineage"]
    nodes = pack["input_observations"]
    active = {key for f, edges in graph.items() if f not in DIAGNOSTICS for key in edges}
    penalties, excluded = [], []
    unique = {}
    for warning in ledger:
        identity = digest(warning)
        unique[identity] = warning
    for identity, warning in unique.items():
        reason = warning["reason"]
        matched = []
        for key in active:
            obs = nodes[key]
            match = False
            if warning.get("fact_ids"):
                match = bool(set(warning["fact_ids"]).intersection(obs.get("fact_ids", [])))
            elif warning.get("parameter"):
                match = warning["parameter"] == obs.get("parameter")
            elif warning.get("source_document_id"):
                match = warning["source_document_id"] in obs.get("source_document_ids", [])
                if warning.get("metric_name"):
                    match = match and warning["metric_name"] == obs.get("metric_name")
                if warning.get("fiscal_period"):
                    match = match and warning["fiscal_period"] == obs.get("period")
            if match:
                matched.append(key)
        target_features = sorted(
            f
            for f, edges in graph.items()
            if f not in DIAGNOSTICS and set(edges).intersection(matched)
        )
        is_quality = reason == "unverified_share_basis" or reason == "registry_quality_issue"
        record = {
            "warning_id": identity,
            "warning": warning,
            "observation_ids": sorted(matched),
            "feature_names": target_features,
        }
        if matched and is_quality:
            record["penalty_kind"] = (
                "share_basis" if reason == "unverified_share_basis" else "quality_issue"
            )
            penalties.append(record)
        else:
            record["exclusion_reason"] = (
                "economic_signal_not_measurement_reliability"
                if reason == "margin_anomaly"
                else "not_a_source_quality_defect"
                if matched
                else "outside_active_feature_lineage_or_unscoped"
            )
            excluded.append(record)
    expected = [
        nodes[key]
        for key in active
        if nodes[key]["kind"] not in ("guidance", "bias_actual")
        and not nodes[key].get("history_absent")
    ]
    completeness = D(sum(o["present"] for o in expected)) / len(expected) if expected else D(0)
    direct_history = [
        nodes[key] for key in active if nodes[key]["kind"] == "actual" and nodes[key]["lag"] > 0
    ]
    history_coverage = (
        D(sum(not o["history_absent"] for o in direct_history)) / len(direct_history)
        if direct_history
        else D(0)
    )
    pack["quality_lineage"] = canonical(
        {
            "active_observation_ids": sorted(active),
            "active_penalties": penalties,
            "excluded_warnings": excluded,
            "observation_completeness": completeness,
            "rolling_history_coverage": history_coverage,
            "required_observations": len(expected),
            "present_observations": sum(o["present"] for o in expected),
            "quality_ledger_preserved": True,
        }
    )
    return pack


def extract_corrected(db, run, previous_runs, policy):
    context: dict[str, Any] = {}
    pack = extract(db, run, previous_runs, policy, context=context)
    data, periods = context["data"], context["periods"]
    nodes: dict[str, Any] = {}
    graph: dict[str, list[str]] = {f: [] for f in pack["features"]}
    source_map = pack["financial_provenance"]["fact_sources"]
    ledger = list(pack["warnings"])

    def add(feature, key, node):
        nodes[key] = canonical(node)
        if key not in graph[feature]:
            graph[feature].append(key)
        return key

    def actual(feature, lag, metric):
        fy, fq = prior_period(data.anchor[0], data.anchor[1], lag)
        q = data.quarter(fy, fq)
        obs = q.metrics.get(metric) if q else None
        parameter = period_name(fy, fq) + ":" + metric
        ids = list(obs.fact_ids) if obs else []
        return add(
            feature,
            "actual:" + parameter,
            {
                "kind": "actual",
                "parameter": parameter,
                "metric_name": metric,
                "period": period_name(fy, fq),
                "lag": lag,
                "history_absent": q is None,
                "present": obs is not None,
                "value": obs.value if obs else None,
                "fact_ids": ids,
                "source_document_ids": sorted(
                    {source_map[str(i)]["source_document_id"] for i in ids if str(i) in source_map}
                ),
                "observation": obs.model_dump(mode="json") if obs else None,
            },
        )

    def refs(feature, lags, metrics):
        for lag in lags:
            for metric in metrics:
                actual(feature, lag, metric)

    refs("revenue_yoy", [0, 4], ["revenue"])
    refs("revenue_qoq", [0, 1], ["revenue"])
    refs("eps_yoy", [0, 4], ["eps_diluted"])
    refs("eps_yoy", [4], ["revenue", "diluted_shares"])
    refs("fcf_yoy", [0, 4], ["fcf"])
    refs("fcf_yoy", [4], ["revenue"])
    refs("growth_acceleration", [0, 1, 4, 5], ["revenue"])
    for margin, metric in (
        ("gross_margin", "gross_profit"),
        ("operating_margin", "operating_income"),
        ("fcf_margin", "fcf"),
    ):
        refs(margin, [0], [metric, "revenue"])
        refs(margin + "_change", [0, 4], [metric, "revenue"])
    refs("operating_leverage", [0, 4], ["operating_income", "revenue"])
    for name, metric in (("ar_growth", "accounts_receivable"), ("inventory_growth", "inventory")):
        refs(name, [0, 4], [metric])
    refs("dso", [0], ["accounts_receivable", "revenue"])
    refs("capex_to_revenue", [0], ["capex", "revenue"])
    refs("sbc_to_revenue", [0], ["sbc", "revenue"])

    def forecast(feature, owner, row, metric):
        if owner is None or row is None:
            return
        cutoff = owner.information_cutoff
        anchor = period_tuple(owner.metadata_json["anchor"])
        dependencies = []
        # M2 uses revenue seasonality through 12 quarters and its previous-quarter denominator.
        allowed = {"revenue": 12}
        if metric in ("gross_margin", "operating_margin", "eps", "free_cash_flow"):
            allowed["gross_profit"] = 3
        if metric in ("operating_margin", "eps", "free_cash_flow"):
            allowed.update(operating_expenses=4, operating_income=3)
        if metric in ("eps", "free_cash_flow"):
            allowed.update(pretax_income=3, tax_expense=3, net_income=3)
        if metric == "eps":
            allowed["diluted_shares"] = 4
        if metric == "free_cash_flow":
            allowed.update(ocf=3, fcf=3, capex=3)
        for parameter, observation in owner.metadata_json["provenance"]["observations"].items():
            period, name = parameter.split(":", 1)
            fy, fq = period_tuple(period)
            lag = anchor[0] * 4 + anchor[1] - (fy * 4 + fq)
            if name not in allowed or not 0 <= lag <= allowed[name]:
                continue
            if (
                aware(datetime.fromisoformat(observation["available_at"].replace("Z", "+00:00")))
                > cutoff
            ):
                raise ValueError("Future forecast dependency")
            key = f"forecast-input:{owner.id}:{parameter}"
            ids = observation["fact_ids"]
            fm = owner.metadata_json["provenance"]["fact_sources"]
            add(
                feature,
                key,
                {
                    "kind": "forecast_input",
                    "parameter": parameter,
                    "period": period,
                    "metric_name": name,
                    "lag": lag,
                    "history_absent": False,
                    "present": True,
                    "fact_ids": ids,
                    "source_document_ids": sorted(
                        {fm[str(i)]["source_document_id"] for i in ids if str(i) in fm}
                    ),
                    "forecast_run_id": owner.id,
                    "information_cutoff": cutoff,
                    "observation": observation,
                },
            )
            dependencies.append(key)
        # Explicit relevant missing-basis inputs may be absent from M2's accepted observations.
        for warning in owner.metadata_json["warnings"]:
            parameter = warning.get("parameter", "")
            if ":" not in parameter:
                continue
            period, name = parameter.split(":", 1)
            if not period.startswith("FY") or name not in allowed:
                continue
            fy, fq = period_tuple(period)
            lag = anchor[0] * 4 + anchor[1] - (fy * 4 + fq)
            if not 0 <= lag <= allowed[name]:
                continue
            key = f"forecast-input:{owner.id}:{parameter}"
            if key not in nodes:
                add(
                    feature,
                    key,
                    {
                        "kind": "forecast_input",
                        "parameter": parameter,
                        "period": period,
                        "metric_name": name,
                        "lag": lag,
                        "present": False,
                        "history_absent": False,
                        "fact_ids": [],
                        "source_document_ids": [],
                        "forecast_run_id": owner.id,
                        "information_cutoff": cutoff,
                    },
                )
            ledger.append(warning)
            dependencies.append(key)
        guide_metrics = (
            ["revenue"]
            + (["gross_margin"] if metric != "revenue" else [])
            + (
                ["operating_expenses"]
                if metric in ("operating_margin", "eps", "free_cash_flow")
                else []
            )
            + (["tax_rate"] if metric in ("eps", "free_cash_flow") else [])
        )
        for name in guide_metrics:
            guide = owner.metadata_json["raw_guidance"].get(name)
            guides = [guide] if guide else []
            bias = owner.metadata_json["guidance_bias"].get(name, {})
            if bias.get("status") == "available":
                for sample in bias["samples"]:
                    guides.append(sample["guidance"])
                    key = f"bias:{owner.id}:{name}:{sample['target']}"
                    ids = sample["actual_fact_ids"]
                    add(
                        feature,
                        key,
                        {
                            "kind": "bias_actual",
                            "present": True,
                            "history_absent": False,
                            "metric_name": name,
                            "period": sample["target"],
                            "fact_ids": ids,
                            "source_document_ids": [],
                            "available_at": sample["actual_available_at"],
                            "forecast_run_id": owner.id,
                        },
                    )
                    dependencies.append(key)
            for guide in guides:
                if aware(datetime.fromisoformat(guide["available_at"])) > cutoff:
                    raise ValueError("Future guidance dependency")
                key = f"guidance:{owner.id}:{guide['id']}"
                add(
                    feature,
                    key,
                    {
                        "kind": "guidance",
                        "present": True,
                        "history_absent": False,
                        "metric_name": name,
                        "period": guide["target"],
                        "fact_ids": [],
                        "source_document_ids": [guide["source_document_id"]],
                        "observation": guide,
                        "forecast_run_id": owner.id,
                    },
                )
                dependencies.append(key)
        key = f"forecast:{owner.id}:{row['id']}:{metric}"
        val = row.get(metric)
        if metric == "operating_margin":
            val = (
                D(row["operating_income"]) / D(row["revenue"])
                if row["operating_income"] is not None and row["revenue"]
                else None
            )
        add(
            feature,
            key,
            {
                "kind": "forecast",
                "present": val is not None,
                "history_absent": False,
                "metric_name": metric,
                "period": f"FY{row['fiscal_year']}",
                "value": val,
                "forecast_run_id": owner.id,
                "forecast_period_id": row["id"],
                "information_cutoff": cutoff,
                "dependencies": dependencies,
                "fact_ids": [],
                "source_document_ids": [],
            },
        )

    fy1 = next(r for r in periods if r["period_type"] == "FY1")
    for horizon in ("NTM", "FY1", "FY2"):
        row = next(r for r in periods if r["period_type"] == horizon)
        for metric in ("revenue", "eps"):
            feature = f"{horizon.lower()}_{metric}_growth"
            forecast(feature, run, row, metric)
            if horizon == "FY2":
                forecast(feature, run, fy1, metric)
                if metric == "eps":
                    forecast(feature, run, fy1, "revenue")
            else:
                lags = (
                    range(4)
                    if horizon == "NTM"
                    else [
                        data.anchor[0] * 4 + data.anchor[1] - ((fy1["fiscal_year"] - 1) * 4 + q)
                        for q in range(1, 5)
                    ]
                )
                refs(
                    feature,
                    lags,
                    ["revenue"]
                    if metric == "revenue"
                    else ["net_income", "diluted_shares", "revenue"],
                )
    for lag in (1, 2, 4):
        prefix = "" if lag == 1 else f"trailing_{lag}q_"
        detail = pack["revision_provenance"][prefix + "revision"]
        older = previous_runs[-lag] if len(previous_runs) >= lag and detail["consecutive"] else None
        previous = (
            next(
                (
                    r
                    for r in stored_periods(db, older.id)
                    if r["period_type"] in ("FY1", "FY2") and r["fiscal_year"] == fy1["fiscal_year"]
                ),
                None,
            )
            if older
            else None
        )
        for metric in ("revenue", "eps", "free_cash_flow", "gross_margin", "operating_margin"):
            name = prefix + ("fcf" if metric == "free_cash_flow" else metric) + "_revision"
            forecast(name, run, fy1, metric)
            forecast(name, older, previous, metric)
            if metric in ("eps", "free_cash_flow"):
                forecast(name, older, previous, "revenue")
        graph[prefix + "revision_breadth"] = sorted(
            {
                key
                for name, edges in graph.items()
                if name.startswith(prefix)
                and name.endswith("_revision")
                and (prefix or not name.startswith("trailing_"))
                for key in edges
            }
        )
    graph["fcf_growth"] = list(graph["fcf_yoy"])
    # Registry findings are observable only after discovery; immutable replay warnings above
    # are instead regenerated from eligible observations, never future ledger content.
    for issue in db.scalars(
        select(DataQualityIssue).where(
            DataQualityIssue.company_id == run.company_id,
            DataQualityIssue.created_at <= run.information_cutoff,
        )
    ):
        effective = issue.details.get("information_available_at")
        if effective and aware(datetime.fromisoformat(effective)) > run.information_cutoff:
            continue
        ledger.append(
            {
                "reason": "registry_quality_issue",
                "issue_id": issue.id,
                "issue_type": issue.issue_type,
                "source_document_id": issue.source_document_id,
                "metric_name": issue.metric_name,
                "fiscal_period": issue.fiscal_period,
                "fact_ids": issue.details.get("fact_ids", []),
            }
        )
    # Attach raw source identity to dependency fact references not already in source maps.
    all_ids = {i for node in nodes.values() for i in node.get("fact_ids", [])}
    for fact in db.scalars(
        select(FinancialFact).where(
            FinancialFact.id.in_(all_ids), FinancialFact.available_at <= run.information_cutoff
        )
    ):
        for node in nodes.values():
            if (
                fact.id in node.get("fact_ids", [])
                and fact.source_document_id not in node["source_document_ids"]
            ):
                node["source_document_ids"].append(fact.source_document_id)
    pack["feature_lineage"] = graph
    pack["input_observations"] = nodes
    return attach_quality(pack, ledger)
