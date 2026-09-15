"""Append-only point-in-time shares outstanding, preserving prior schemas/data."""

import sqlalchemy as sa
from alembic import op

from valuation_engine.db.schema import ExactNumeric, UTCDateTime
from valuation_engine.db.session import install_immutability

revision = "0004_pit_shares"
down_revision = "0003_exact_decimals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "share_count_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("identity_key", sa.String(64), nullable=False, unique=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("share_class", sa.String(), nullable=False),
        sa.Column("share_count", ExactNumeric(30, 8), nullable=False),
        sa.Column("shares_as_of_date", sa.Date(), nullable=False),
        sa.Column("published_at", UTCDateTime(), nullable=False),
        sa.Column("available_at", UTCDateTime(), nullable=False),
        sa.Column(
            "source_document_id", sa.Integer(), sa.ForeignKey("source_documents.id"), nullable=False
        ),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("taxonomy_concept", sa.String(), nullable=True),
        sa.Column("split_basis", sa.JSON(), nullable=False),
        sa.Column("normalized_share_count", ExactNumeric(30, 8), nullable=False),
        sa.Column("normalized_basis_date", sa.Date(), nullable=False),
        sa.Column("confidence", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("available_at >= published_at", name="share_availability"),
    )
    for field in ("company_id", "shares_as_of_date", "available_at"):
        op.create_index(f"ix_share_count_observations_{field}", "share_count_observations", [field])
    install_immutability(op.get_bind(), ("share_count_observations",))


def downgrade():
    raise RuntimeError("Share provenance is append-only; restore an audited pre-migration backup.")
