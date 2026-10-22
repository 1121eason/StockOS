"""Chronological immutable regime persistence; no valuation or evaluation access."""

from sqlalchemy import select

from valuation_engine.db.schema import AssumptionSet, RegimeSnapshot, RegimeTransition
from valuation_engine.db.store import digest
from valuation_engine.regime.features import eligible_runs, extract
from valuation_engine.regime.policy import POLICY, REGIMES, classify
from valuation_engine.research.numbers import D, canonical


def payload(policy):
    result = {
        "policy": policy,
        "implementation_version": "RegimeEngineV1.1-confidence-streak",
        "unit_contract": {
            "scores": "signed_unit_interval",
            "probabilities": "fraction",
            "cycle_score": "signed_percent",
            "growth_revision_thresholds": "fraction",
            "margins": "fraction",
            "samples": "observations",
            "persistence": "quarters",
        },
        "source_reference": "regime/policy_v1.json; docs/REGIME_METHOD.md",
        "selection": "fixed_a_priori_not_return_fitted",
    }
    if policy.get("confidence_model"):
        result["implementation_version"] = "RegimeEngineV1.2-active-lineage"
        result["source_reference"] = (
            "regime/policy_v1_1.json; docs/REGIME_METHOD.md; docs/REGIME_OUTPUT_CONTRACT.md"
        )
    return result


def replay(db, company_id, cutoff, policy=POLICY):
    return replay_runs(db, company_id, eligible_runs(db, company_id, cutoff), policy)


def replay_runs(db, company_id, runs, policy=POLICY, *, allow_live=False):
    """Shared classifier; product callers must supply one chronological run per quarter."""
    if allow_live:
        anchors = [r.metadata_json["anchor"] for r in runs]
        if anchors != sorted(set(anchors)) or any(r.company_id != company_id for r in runs):
            raise ValueError("Live regime requires unique chronological fiscal quarters")
    assumptions = payload(policy)
    key = digest(assumptions)
    assumption = db.scalar(select(AssumptionSet).where(AssumptionSet.content_hash == key))
    if assumption is None:
        assumption = AssumptionSet(content_hash=key, assumptions=assumptions)
        db.add(assumption)
        db.flush()
    if not runs:
        raise ValueError("No eligible formal M2 first-tradable forecasts; run M2 first")
    states: list[dict] = []
    records: list[RegimeSnapshot] = []
    packs: list[dict] = []
    for index, run in enumerate(runs):
        if policy.get("confidence_model"):
            from valuation_engine.regime.confidence import classify_corrected
            from valuation_engine.regime.lineage import extract_corrected

            pack = extract_corrected(db, run, runs[:index], policy, allow_live=allow_live)
            state = classify_corrected(pack, states, policy)
        else:
            pack = extract(db, run, runs[:index], policy, allow_live=allow_live)
            state = classify(pack, states, policy)
        prior = records[-1] if records else None
        identity = digest(
            {
                "inputs": pack,
                "state": state,
                "assumption_hash": key,
                "previous_identity": prior.identity_key if prior else None,
            }
        )
        row = db.scalar(select(RegimeSnapshot).where(RegimeSnapshot.identity_key == identity))
        if row is None:
            row = RegimeSnapshot(
                identity_key=identity,
                company_id=company_id,
                as_of_timestamp=run.forecast_as_of,
                regime=state["primary_regime"],
                primary_regime=state["primary_regime"],
                model_version=policy["version"],
                policy_version=policy["version"],
                assumption_set_id=assumption.id,
                input_snapshot_id=run.input_snapshot_id,
                forecast_run_id=run.id,
                previous_snapshot_id=prior.id if prior else None,
                metadata_json={"inputs": pack, "state": state, "assumption_hash": key},
                confidence=D(state["confidence"]),
                data_quality_score=D(state["data_quality_score"]),
                cycle_score=D(state["cycle_score"]) if state["cycle_score"] is not None else None,
                **{
                    k + "_score": D(v) if v is not None else None
                    for k, v in state["scores"].items()
                },
                **{
                    r.lower().replace(" ", "_") + "_probability": D(state["probabilities"][r])
                    for r in REGIMES
                },
            )
            if policy.get("confidence_model"):
                for field in ("confirmed_regime", "candidate_regime", "transition_status"):
                    setattr(row, field, state[field])
                for field in (
                    "evidence_confidence",
                    "data_quality_confidence",
                    "history_sufficiency",
                    "composite_confidence",
                    "candidate_probability",
                    "probability_gap_to_second_candidate",
                ):
                    setattr(row, field, D(state[field]))
            db.add(row)
            db.flush()
        if (
            prior
            and state["previous_regime"] is not None
            and prior.primary_regime != row.primary_regime
        ):
            transition_key = digest([prior.identity_key, row.identity_key])
            transition = db.scalar(
                select(RegimeTransition).where(RegimeTransition.identity_key == transition_key)
            )
            if transition is None:
                db.add(
                    RegimeTransition(
                        identity_key=transition_key,
                        company_id=company_id,
                        from_regime=prior.primary_regime,
                        to_regime=row.primary_regime,
                        effective_at=run.forecast_as_of,
                        detected_at=run.forecast_as_of,
                        previous_snapshot_id=prior.id,
                        new_snapshot_id=row.id,
                        transition_strength=D(state["transition_strength"]),
                        reason_codes=state["reason_codes"],
                        policy_version=policy["version"],
                    )
                )
                db.flush()
        records.append(row)
        states.append(state)
        packs.append(pack)
    return records, states, packs


def transitions(db, snapshot_ids):
    return [
        canonical({c.name: getattr(r, c.name) for c in r.__table__.columns})
        for r in db.scalars(
            select(RegimeTransition)
            .where(RegimeTransition.new_snapshot_id.in_(snapshot_ids))
            .order_by(RegimeTransition.effective_at, RegimeTransition.id)
        )
    ]
