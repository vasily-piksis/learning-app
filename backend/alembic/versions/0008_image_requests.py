"""Durable image attempt accounting, independent of removable study payload."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "image_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("reserved_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.UniqueConstraint("job_id", "attempt_no"),
        sa.UniqueConstraint("user_id", "request_key"),
    )
    op.create_index("ix_image_requests_reserved_at", "image_requests", ["reserved_at"])


def downgrade():
    raise RuntimeError("Restore a complete backup rather than erasing paid request accounting")
