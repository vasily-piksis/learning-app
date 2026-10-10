"""Retained YouTube transcript sources and timed segments."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("source_url", sa.Text(), nullable=True))
    op.add_column(
        "documents", sa.Column("source_meta", sa.JSON(), server_default="{}", nullable=False)
    )
    op.add_column("source_pages", sa.Column("start_seconds", sa.Float(), nullable=True))
    op.add_column("source_pages", sa.Column("end_seconds", sa.Float(), nullable=True))


def downgrade():
    raise RuntimeError("Destructive downgrades are disabled; restore a backup instead")
