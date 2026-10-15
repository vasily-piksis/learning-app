"""Private asynchronous evaluations and text-free paid-attempt accounting."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_card_id", sa.Integer(), sa.ForeignKey("session_cards.id"), nullable=False
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("request_keys", sa.JSON(), nullable=False),
        sa.Column("submission", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("staged_result", sa.JSON(), nullable=True),
        sa.Column("applied_result", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("updated", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_card_id"),
        sa.UniqueConstraint("user_id", "request_key"),
        sqlite_autoincrement=True,
    )
    op.create_table(
        "evaluation_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("reserved_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.UniqueConstraint("job_id", "attempt_no"),
    )
    op.create_index("ix_evaluation_requests_reserved_at", "evaluation_requests", ["reserved_at"])


def downgrade():
    raise RuntimeError("Restore a complete backup rather than erasing paid request accounting")
