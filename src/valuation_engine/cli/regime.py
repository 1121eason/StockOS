"""Human-readable financial regime commands."""

from sqlalchemy.orm import Session

from valuation_engine.cli.research import at_time, emit, fmt, require_ticker
from valuation_engine.config import Settings
from valuation_engine.db.session import engine
from valuation_engine.regime.confidence import POLICY as CORRECTED_POLICY
from valuation_engine.regime.confidence import snapshot_contract
from valuation_engine.regime.policy import POLICY as LEGACY_POLICY
from valuation_engine.regime.service import replay, transitions
from valuation_engine.research.numbers import D

REASON_TEXT = {
    "INITIAL_STATE": "Initial classification; confidence reflects available history.",
    "STATE_RETAINED": "The confirmed fundamental state remains unchanged.",
    "PERSISTENCE_PENDING": "A different candidate is awaiting sufficient consecutive evidence.",
    "PERSISTENCE_CONFIRMED": "Consecutive qualifying quarters confirm the new state.",
    "STRONG_EVIDENCE_TRANSITION": "Strong evidence across multiple dimensions permits an immediate transition.",
    "STRONG_NEGATIVE_OVERRIDE": "Broad, severe financial deterioration overrides the normal waiting period.",
    "STRUCTURAL_GUARD_RELEASED": "The required structural evidence window no longer holds.",
    "GROWTH_ACCELERATION": "Revenue growth is accelerating.",
    "GROWTH_DECELERATION": "Revenue growth is slowing.",
    "REVISION_ACCELERATION": "The same fiscal-year EPS forecast has been revised upward.",
    "MARGIN_COMPRESSION": "Operating margin is below the comparable prior-year quarter.",
    "CYCLICAL_PRESSURE": "Receivables or inventory growth is outpacing revenue.",
    "CASH_FLOW_DIVERGENCE": "FCF growth is trailing revenue growth.",
    "PERSISTENT_NEGATIVE_REVISIONS": "Negative revisions accompany sustained multi-dimensional stress.",
    "NEGATIVE_REVISION_SHOCK": "Negative revisions accompany a new multi-dimensional stress observation.",
    "RECOVERY": "The confirmed state has recovered from a downturn or deterioration classification.",
    "STRUCTURAL_EVIDENCE_INSUFFICIENT": "The required evidence for structural deterioration is not present.",
    "INCOMPLETE_OR_ANOMALOUS_INPUTS": "Missing inputs or warning flags reduce data quality and confidence.",
}


def run(ticker, as_of, view, json_output, policy_version="RegimePolicyV1.1"):
    if policy_version not in ("RegimePolicyV1", "RegimePolicyV1.1"):
        raise ValueError("Unsupported regime policy")
    policy = CORRECTED_POLICY if policy_version == "RegimePolicyV1.1" else LEGACY_POLICY
    require_ticker(ticker)
    with Session(engine(Settings().qve_database_url)) as db:
        records, states, packs = replay(db, 1, at_time(as_of), policy)
        events = transitions(db, [r.id for r in records])
        db.commit()
        result = {"states": states, "transitions": events, "snapshot_ids": [r.id for r in records]}
        if json_output:
            if policy_version == "RegimePolicyV1.1":
                envelopes = [snapshot_contract(row) for row in records]
                result["states"] = envelopes
                emit(result if view in ("history", "transitions") else envelopes[-1])
            else:
                emit(result if view in ("history", "transitions") else states[-1])
            return
        import typer

        if view == "transitions":
            for event in events:
                typer.echo(
                    f"{event['effective_at']} | {event['from_regime']} → {event['to_regime']} | {', '.join(event['reason_codes'])}"
                )
            if not events:
                typer.echo("No confirmed transitions")
            return
        if view == "history":
            for state in states:
                typer.echo(
                    f"{state['quarter']} | {state['primary_regime']} | candidate {state['candidate_regime']} | Cycle {fmt(state['cycle_score'])} | Confidence {fmt(state['confidence'], True)}"
                )
                if policy_version == "RegimePolicyV1.1":
                    typer.echo(
                        f"  {state['transition_status']} | Evidence {fmt(state['evidence_confidence'], True)} | DQ {fmt(state['data_quality_confidence'], True)} | History {fmt(state['history_sufficiency'], True)} | Candidate p {fmt(state['candidate_probability'], True)} | Gap {fmt(state['probability_gap_to_second_candidate'], True)} | Counter {state['candidate_streak']}"
                    )
            return
        state = states[-1]
        typer.echo(
            f"NVDA | {state['quarter']} | First-tradable {state['as_of']}\nResearch reconstructed / {policy_version}\nPrimary Regime: {state['primary_regime']}\nCandidate: {state['candidate_regime']}\nCycle Score: {fmt(state['cycle_score'])}"
        )
        if policy_version == "RegimePolicyV1.1":
            typer.echo(
                f"Transition: {state['transition_status']} | Evidence {fmt(state['evidence_confidence'], True)} | Data quality {fmt(state['data_quality_confidence'], True)} | History sufficiency {fmt(state['history_sufficiency'], True)} | Composite {fmt(state['composite_confidence'], True)}"
            )
            typer.echo(
                f"Candidate probability {fmt(state['candidate_probability'], True)} | Gap to runner-up {fmt(state['probability_gap_to_second_candidate'], True)} | Confirmation counter {state['candidate_streak']}"
            )
        if view == "cycle":
            for key, value in state["cycle_components"].items():
                typer.echo(f"{key}: {fmt(value)}")
            return
        typer.echo("\nModel confidence normalization (not calibrated probabilities):")
        for regime, probability in state["probabilities"].items():
            typer.echo(f"{regime:28} {fmt(probability, True)}")
        typer.echo("\nScores [-1,+1]:")
        for key, value in state["scores"].items():
            typer.echo(f"{key}: {fmt(value)}")
        typer.echo(
            f"\nConfidence: {fmt(state['confidence'], True)} | Data quality: {fmt(state['data_quality_score'], True)}\nStructural stress window: {state['stress_streak']} quarters"
        )
        typer.echo("\nPrimary reasons (deterministic rules):")
        for code in state["reason_codes"]:
            typer.echo(f"- {REASON_TEXT[code]} [{code}]")
        typer.echo(
            f"Realized forecast-error samples: {fmt(packs[-1]['features']['forecast_sample_count'])}"
        )
        if state["candidate_regime"] != state["primary_regime"]:
            typer.echo(
                "Primary state is retained by persistence; probabilities describe instantaneous evidence."
            )
        assert sum(D(v) for v in state["probabilities"].values()) == 1


def register(app):
    @app.command("regime")
    def regime(
        ticker: str = "NVDA",
        as_of: str | None = None,
        json_output: bool = False,
        policy_version: str = "RegimePolicyV1.1",
    ):
        run(ticker, as_of, "snapshot", json_output, policy_version)

    @app.command("regime-history")
    def history(
        ticker: str = "NVDA",
        as_of: str | None = None,
        json_output: bool = False,
        policy_version: str = "RegimePolicyV1.1",
    ):
        run(ticker, as_of, "history", json_output, policy_version)

    @app.command("regime-transitions")
    def changes(
        ticker: str = "NVDA",
        as_of: str | None = None,
        json_output: bool = False,
        policy_version: str = "RegimePolicyV1.1",
    ):
        run(ticker, as_of, "transitions", json_output, policy_version)

    @app.command("cycle-score")
    def cycle(
        ticker: str = "NVDA",
        as_of: str | None = None,
        json_output: bool = False,
        policy_version: str = "RegimePolicyV1.1",
    ):
        run(ticker, as_of, "cycle", json_output, policy_version)
