from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from valuation_engine.db.schema import Base

IMMUTABLE = (
    "financial_facts",
    "forecast_snapshots",
    "assumption_sets",
    "quarterly_snapshots",
    "quant_features",
    "guidance_items",
    "segment_facts",
    "source_documents",
    "valuation_snapshots",
)


HARDENED_IMMUTABLE = (
    "availability_evidence",
    "corporate_actions",
    "price_bases",
    "reconciliation_results",
    "quality_reviews",
    "share_count_observations",
)

AI_IMMUTABLE = (
    "ai_analysis_runs",
    "ai_analysis_events",
    "ai_provider_calls",
    "ai_evidence",
    "ai_analyst_features",
    "ai_feature_evidence",
    "ai_analyst_snapshots",
    "ai_challenges",
    "model_adjustment_proposals",
    "ai_unsupported_claims",
    "ai_human_reviews",
)

REGIME_IMMUTABLE = ("regime_snapshots", "regime_transitions")

RESEARCH_IMMUTABLE = (
    "forecast_runs",
    "forecast_periods",
    "forecast_assumptions",
    "forecast_revisions",
    "research_valuations",
    "dcf_scenarios",
)


def engine(url: str) -> Engine:
    result = create_engine(url)
    if result.dialect.name == "sqlite":

        @event.listens_for(result, "connect")
        def foreign_keys(conn, _record):  # type: ignore[no-untyped-def]
            conn.execute("PRAGMA foreign_keys=ON")

    return result


def install_immutability(connection, tables=IMMUTABLE):  # type: ignore[no-untyped-def]
    if connection.dialect.name == "sqlite":
        for name in tables:
            for action in ("UPDATE", "DELETE"):
                connection.execute(
                    text(
                        f"CREATE TRIGGER IF NOT EXISTS immutable_{name}_{action.lower()} BEFORE {action} ON {name} BEGIN SELECT RAISE(ABORT, 'immutable record'); END"
                    )
                )
    elif connection.dialect.name == "postgresql":
        connection.execute(
            text(
                "CREATE OR REPLACE FUNCTION qve_reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable record'; END; $$"
            )
        )
        for name in tables:
            connection.execute(
                text(
                    f"CREATE TRIGGER immutable_{name} BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION qve_reject_mutation()"
                )
            )


def create_test_schema(url: str) -> Engine:
    result = engine(url)
    Base.metadata.create_all(result)
    with result.begin() as conn:
        install_immutability(
            conn,
            IMMUTABLE + HARDENED_IMMUTABLE + RESEARCH_IMMUTABLE + REGIME_IMMUTABLE + AI_IMMUTABLE,
        )
    return result


def session(url: str) -> Session:
    return Session(engine(url))
