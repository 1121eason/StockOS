"""Add immutable M2 research records; M1.1 rows and semantics remain unchanged."""

import sqlalchemy as sa
from alembic import op

from valuation_engine.db.schema import UTCDateTime
from valuation_engine.db.session import install_immutability

revision = "0003_forecast_outcomes"
down_revision = "0002_labels_exact"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "forecast_outcomes",
        sa.Column("identity_key", sa.String(), nullable=False),
        sa.Column("forecast_run_key", sa.String(), nullable=False),
        sa.Column("evaluation_as_of", UTCDateTime(), nullable=False),
        sa.Column("available_at", UTCDateTime(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("horizon", sa.String(), nullable=False),
        sa.Column("fiscal_period", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("identity_key"),
    )
    install_immutability(op.get_bind(), ("forecast_outcomes",))


def downgrade():
    raise RuntimeError("Immutable research outputs require an audited backup to roll back")
