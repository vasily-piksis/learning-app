"""Keep stable subject identifiers when removing their library contents."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "subjects", sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade():
    raise RuntimeError("Destructive downgrades are disabled; restore a backup instead")
