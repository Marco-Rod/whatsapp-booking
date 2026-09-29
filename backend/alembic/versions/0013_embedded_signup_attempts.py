"""Add ephemeral application correlation attempts for Embedded Signup."""

from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "embedded_signup_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "business_id",
            sa.Integer(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nonce_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("nonce_hash", name="uq_embedded_signup_attempt_nonce_hash"),
    )
    op.create_index(
        "ix_embedded_signup_attempts_business_id",
        "embedded_signup_attempts",
        ["business_id"],
    )
    op.create_index(
        "ix_embedded_signup_attempts_expires_at",
        "embedded_signup_attempts",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_embedded_signup_attempts_expires_at", table_name="embedded_signup_attempts")
    op.drop_index("ix_embedded_signup_attempts_business_id", table_name="embedded_signup_attempts")
    op.drop_table("embedded_signup_attempts")
