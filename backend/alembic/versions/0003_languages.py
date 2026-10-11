"""Preserve source and question languages without rewriting old content."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("source_pages", sa.Column("language", sa.String(20), nullable=True))
    op.add_column("cards", sa.Column("language", sa.String(20), nullable=True))
    op.add_column("cards", sa.Column("target_language", sa.String(20), nullable=True))


def downgrade():
    raise RuntimeError("Destructive downgrades are disabled; restore a backup instead")
