"""Add typed exercises without changing existing questions or history."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cards", sa.Column("question_type", sa.String(40), nullable=False, server_default="choice")
    )
    op.add_column("cards", sa.Column("exercise", sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError("Destructive downgrades are disabled; restore a backup instead")
