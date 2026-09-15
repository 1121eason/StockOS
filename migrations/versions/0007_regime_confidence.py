"""Explicit M3.1 confidence/transition fields; preserve immutable V1 rows as NULL."""

import sqlalchemy as sa
from alembic import op

from valuation_engine.db.schema import ExactNumeric

revision = "0007_regime_confidence"
down_revision = "0006_regimes"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("confirmed_regime", "candidate_regime", "transition_status"):
        op.add_column("regime_snapshots", sa.Column(name, sa.String(), nullable=True))
    for name in (
        "evidence_confidence",
        "data_quality_confidence",
        "history_sufficiency",
        "composite_confidence",
        "candidate_probability",
        "probability_gap_to_second_candidate",
    ):
        op.add_column("regime_snapshots", sa.Column(name, ExactNumeric(20, 8), nullable=True))


def downgrade():
    raise RuntimeError(
        "Restore a verified baseline; immutable regime history is not downgraded in place"
    )
