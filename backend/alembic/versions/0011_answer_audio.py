"""Private audio and text-free per-send duration accounting."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audio_answers",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "session_card_id", sa.Integer(), sa.ForeignKey("session_cards.id"), nullable=True
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("request_keys", sa.JSON(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("duration", sa.Float(), nullable=False),
        sa.Column("raw_path", sa.String(80), nullable=True),
        sa.Column("expected_language", sa.String(35), nullable=False),
        sa.Column("detected_languages", sa.JSON(), nullable=False),
        sa.Column("original_transcript", sa.Text(), nullable=True),
        sa.Column("was_edited", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "request_key"),
    )
    op.create_index("ix_audio_answers_session_card_id", "audio_answers", ["session_card_id"])
    op.create_table(
        "transcription_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(80), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column("reserved_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.UniqueConstraint("user_id", "request_key"),
    )
    op.create_index(
        "ix_transcription_requests_reserved_at", "transcription_requests", ["reserved_at"]
    )


def downgrade():
    raise RuntimeError("Restore a complete backup rather than erasing paid request accounting")
