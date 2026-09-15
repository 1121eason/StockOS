"""Preserve exact decimal values on SQLite; native PostgreSQL NUMERIC stays unchanged."""

from alembic import op

from valuation_engine.db.decimal_migration_v3 import migrate_decimal_storage

revision = "0003_exact_decimals"
down_revision = "0002_hardening"
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
    raise RuntimeError(
        "Lossy decimal downgrade is intentionally unsupported; restore a retained pre-migration backup"
    )
