"""Exact decimal storage for isolated historical labels."""

from alembic import op

from valuation_engine.db.decimal_migration_v3 import migrate_decimal_storage

revision = "0002_labels_exact"
down_revision = "0001_labels"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().as_sql:
        if op.get_bind().dialect.name == "sqlite":
            raise RuntimeError("SQLite precision migration requires online preservation checks")
        return
    op.get_context().config.attributes["numeric_storage_audit"] = migrate_decimal_storage(
        op.get_bind()
    )


def downgrade():
    raise RuntimeError("Lossy decimal downgrade unsupported; restore a pre-migration backup")
