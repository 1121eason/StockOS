"""Add immutable M2 research records; M1.1 rows and semantics remain unchanged."""

import sqlalchemy as sa
from alembic import op

from valuation_engine.db.schema import ExactNumeric, UTCDateTime
from valuation_engine.db.session import install_immutability

revision = "0005_research"
down_revision = "0004_pit_shares"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "forecast_runs",
        sa.Column("identity_key", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("forecast_as_of", UTCDateTime(), nullable=False),
        sa.Column("information_cutoff", UTCDateTime(), nullable=False),
        sa.Column("tradable_at", UTCDateTime(), nullable=False),
        sa.Column("forecast_type", sa.String(), nullable=False),
        sa.Column("forecast_basis", sa.String(), nullable=False),
        sa.Column("generated_kind", sa.String(), nullable=False),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column(
            "assumption_set_id", sa.Integer(), sa.ForeignKey("assumption_sets.id"), nullable=False
        ),
        sa.Column(
            "input_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("quarterly_snapshots.id"),
            nullable=False,
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("identity_key"),
    )
    op.create_index("ix_forecast_runs_forecast_as_of", "forecast_runs", ["forecast_as_of"])
    op.create_table(
        "forecast_periods",
        sa.Column(
            "forecast_run_id", sa.Integer(), sa.ForeignKey("forecast_runs.id"), nullable=False
        ),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_quarter", sa.Integer(), nullable=False),
        sa.Column("period_type", sa.String(), nullable=False),
        sa.Column("revenue", ExactNumeric(30, 8), nullable=True),
        sa.Column("gross_margin", ExactNumeric(20, 8), nullable=True),
        sa.Column("gross_profit", ExactNumeric(30, 8), nullable=True),
        sa.Column("operating_expenses", ExactNumeric(30, 8), nullable=True),
        sa.Column("operating_income", ExactNumeric(30, 8), nullable=True),
        sa.Column("non_operating_income", ExactNumeric(30, 8), nullable=True),
        sa.Column("pre_tax_income", ExactNumeric(30, 8), nullable=True),
        sa.Column("tax_rate", ExactNumeric(20, 8), nullable=True),
        sa.Column("net_income", ExactNumeric(30, 8), nullable=True),
        sa.Column("diluted_weighted_shares", ExactNumeric(30, 8), nullable=True),
        sa.Column("eps", ExactNumeric(30, 8), nullable=True),
        sa.Column("operating_cash_flow", ExactNumeric(30, 8), nullable=True),
        sa.Column("capex", ExactNumeric(30, 8), nullable=True),
        sa.Column("free_cash_flow", ExactNumeric(30, 8), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("forecast_run_id", "period_type", "fiscal_year", "fiscal_quarter"),
    )
    op.create_index("ix_forecast_periods_forecast_run_id", "forecast_periods", ["forecast_run_id"])
    op.create_table(
        "forecast_assumptions",
        sa.Column(
            "assumption_set_id", sa.Integer(), sa.ForeignKey("assumption_sets.id"), nullable=False
        ),
        sa.Column("parameter_name", sa.String(), nullable=False),
        sa.Column("parameter_value", sa.JSON(), nullable=False),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_reference", sa.String(), nullable=False),
        sa.Column("effective_from", UTCDateTime(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("assumption_set_id", "parameter_name"),
    )
    op.create_table(
        "forecast_revisions",
        sa.Column("identity_key", sa.String(), nullable=False),
        sa.Column(
            "previous_run_id", sa.Integer(), sa.ForeignKey("forecast_runs.id"), nullable=False
        ),
        sa.Column(
            "forecast_run_id", sa.Integer(), sa.ForeignKey("forecast_runs.id"), nullable=False
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("identity_key"),
    )
    op.create_table(
        "research_valuations",
        sa.Column("identity_key", sa.String(), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "forecast_run_id", sa.Integer(), sa.ForeignKey("forecast_runs.id"), nullable=False
        ),
        sa.Column(
            "source_valuation_id",
            sa.Integer(),
            sa.ForeignKey("valuation_snapshots.id"),
            nullable=False,
        ),
        sa.Column("as_of_timestamp", UTCDateTime(), nullable=False),
        sa.Column("valuation_model_version", sa.String(), nullable=False),
        sa.Column("ntm_pe", ExactNumeric(30, 8), nullable=True),
        sa.Column("fy1_pe", ExactNumeric(30, 8), nullable=True),
        sa.Column("fy2_pe", ExactNumeric(30, 8), nullable=True),
        sa.Column("forward_fcf_yield", ExactNumeric(30, 8), nullable=True),
        sa.Column("forward_ev_ebit", ExactNumeric(30, 8), nullable=True),
        sa.Column("historical_ntm_pe_percentile", ExactNumeric(20, 8), nullable=True),
        sa.Column("historical_ntm_pe_zscore", ExactNumeric(20, 8), nullable=True),
        sa.Column("dcf_base", ExactNumeric(30, 8), nullable=True),
        sa.Column("dcf_low", ExactNumeric(30, 8), nullable=True),
        sa.Column("dcf_high", ExactNumeric(30, 8), nullable=True),
        sa.Column("reverse_dcf_implied_fcf_cagr", ExactNumeric(20, 8), nullable=True),
        sa.Column("internal_fcf_cagr", ExactNumeric(20, 8), nullable=True),
        sa.Column("expectations_gap", ExactNumeric(20, 8), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("identity_key"),
    )
    op.create_index(
        "ix_research_valuations_as_of_timestamp", "research_valuations", ["as_of_timestamp"]
    )
    op.create_table(
        "dcf_scenarios",
        sa.Column(
            "valuation_id", sa.Integer(), sa.ForeignKey("research_valuations.id"), nullable=False
        ),
        sa.Column("wacc", ExactNumeric(16, 8), nullable=False),
        sa.Column("terminal_growth", ExactNumeric(16, 8), nullable=False),
        sa.Column("enterprise_value", ExactNumeric(30, 8), nullable=True),
        sa.Column("equity_value", ExactNumeric(30, 8), nullable=True),
        sa.Column("per_share", ExactNumeric(30, 8), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("valuation_id", "wacc", "terminal_growth"),
    )
    install_immutability(
        op.get_bind(),
        (
            "forecast_runs",
            "forecast_periods",
            "forecast_assumptions",
            "forecast_revisions",
            "research_valuations",
            "dcf_scenarios",
        ),
    )


def downgrade():
    raise RuntimeError("Immutable research outputs require an audited backup to roll back")
