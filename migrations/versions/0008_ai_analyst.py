"""Append-only M4 AI runs, evidence, features and advisory outputs; no Quant changes."""

from alembic import op

from valuation_engine.db.schema import Base
from valuation_engine.db.session import AI_IMMUTABLE, install_immutability

revision = "0008_ai_analyst"
down_revision = "0007_regime_confidence"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    for table in Base.metadata.sorted_tables:
        if table.name in AI_IMMUTABLE:
            table.create(conn, checkfirst=True)
    install_immutability(conn, AI_IMMUTABLE)


def downgrade():
    raise RuntimeError("Restore a verified backup; do not erase immutable AI research history")
