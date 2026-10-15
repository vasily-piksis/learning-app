"""Image source roles and non-resurrecting upload idempotency."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("card_images", "session_images"):
        op.add_column(
            table,
            sa.Column("image_role", sa.String(20), nullable=False, server_default="illustration"),
        )
    op.create_table(
        "picture_draft_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("card_id", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "key"),
    )


def downgrade():
    raise RuntimeError("Restore a complete backup to preserve source roles and upload tombstones")
