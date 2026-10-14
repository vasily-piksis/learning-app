"""Private immutable image assets and versioned references."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "image_assets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("filename", sa.String(80), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("mime", sa.String(40), nullable=False),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_card_id", sa.Integer(), sa.ForeignKey("cards.id"), nullable=True),
        sa.Column("target_version", sa.Integer(), nullable=True),
        sa.Column("slot", sa.String(20), nullable=True),
        sa.Column("provider_meta", sa.JSON(), nullable=False),
        sa.Column("created", sa.DateTime(), nullable=False),
        sa.Column("updated", sa.DateTime(), nullable=False),
    )
    for field in ["stage", "owner_user_id", "target_card_id"]:
        op.create_index(f"ix_image_assets_{field}", "image_assets", [field])
    for table, parent, key in [
        ("card_images", "cards", "card_id"),
        ("session_images", "session_cards", "session_card_id"),
    ]:
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                key,
                sa.Integer(),
                sa.ForeignKey(
                    f"{parent}.id", ondelete="CASCADE" if table == "session_images" else None
                ),
                nullable=False,
            ),
            sa.Column("asset_id", sa.String(32), sa.ForeignKey("image_assets.id"), nullable=False),
            sa.Column("slot", sa.String(20), nullable=False),
            sa.Column("alt", sa.String(500), nullable=False),
            sa.UniqueConstraint(key, "slot"),
        )
        op.create_index(f"ix_{table}_{key}", table, [key])
        op.create_index(f"ix_{table}_asset_id", table, ["asset_id"])
    op.create_table(
        "job_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("asset_id", sa.String(32), sa.ForeignKey("image_assets.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.UniqueConstraint("job_id", "asset_id", "role"),
    )
    for field in ["job_id", "asset_id"]:
        op.create_index(f"ix_job_images_{field}", "job_images", [field])


def downgrade():
    raise RuntimeError("Restore a complete backup rather than deleting private images")
