"""Keep history identifiers and support multiple correct answers."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "topics", sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "cards", sa.Column("correct_indices", sa.JSON(), nullable=False, server_default="[]")
    )


def downgrade():
    raise RuntimeError("Destructive downgrades are disabled; restore a backup instead")
