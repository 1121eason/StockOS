"""Add M3 immutable regime fields and append-only transitions; preserve legacy rows."""

import sqlalchemy as sa
from alembic import op

from valuation_engine.db.schema import ExactNumeric, UTCDateTime
from valuation_engine.db.session import install_immutability

revision = "0006_regimes"
down_revision = "0005_research"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("regime_snapshots") as batch:
        for name in ("identity_key", "primary_regime", "policy_version"):
            batch.add_column(sa.Column(name, sa.String(), nullable=True))
        for name, target in (
            ("assumption_set_id", "assumption_sets"),
            ("input_snapshot_id", "quarterly_snapshots"),
            ("forecast_run_id", "forecast_runs"),
            ("previous_snapshot_id", "regime_snapshots"),
        ):
            batch.add_column(sa.Column(name, sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_regime_" + name, target, [name], ["id"])
        batch.add_column(sa.Column("metadata_json", sa.JSON(), nullable=True))
        for name in (
            "growth_score",
            "revision_score",
            "profitability_score",
            "cash_quality_score",
            "deterioration_score",
            "cycle_score",
            "confidence",
            "data_quality_score",
        ):
            batch.add_column(sa.Column(name, ExactNumeric(20, 8), nullable=True))
        batch.create_unique_constraint("uq_regime_identity", ["identity_key"])
    op.create_table(
        "regime_transitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("identity_key", sa.String(), nullable=False, unique=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("from_regime", sa.String(), nullable=False),
        sa.Column("to_regime", sa.String(), nullable=False),
        sa.Column("effective_at", UTCDateTime(), nullable=False),
        sa.Column("detected_at", UTCDateTime(), nullable=False),
        sa.Column(
            "previous_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("regime_snapshots.id"),
            nullable=False,
        ),
        sa.Column(
            "new_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("regime_snapshots.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("transition_strength", ExactNumeric(20, 8), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(), nullable=False),
    )
    install_immutability(op.get_bind(), ("regime_snapshots", "regime_transitions"))


def downgrade():
    raise RuntimeError("Regime history is immutable; restore a verified pre-M3 backup instead")
