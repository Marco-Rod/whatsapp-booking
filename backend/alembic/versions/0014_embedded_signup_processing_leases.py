"""Add recoverable processing leases to Embedded Signup attempts."""

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "embedded_signup_attempts",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="ready",
        ),
    )
    op.add_column(
        "embedded_signup_attempts",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "embedded_signup_attempts",
        sa.Column("processing_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "embedded_signup_attempts",
        sa.Column("processing_lease_hash", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE embedded_signup_attempts "
        "SET status = 'consumed' "
        "WHERE consumed_at IS NOT NULL"
    )
    op.create_index(
        "ix_embedded_signup_attempts_processing_expires_at",
        "embedded_signup_attempts",
        ["status", "processing_expires_at"],
    )
    op.create_check_constraint(
        "ck_embedded_signup_attempt_lifecycle",
        "embedded_signup_attempts",
        "(status = 'ready' AND consumed_at IS NULL "
        "AND processing_started_at IS NULL "
        "AND processing_expires_at IS NULL "
        "AND processing_lease_hash IS NULL) "
        "OR (status = 'processing' AND consumed_at IS NULL "
        "AND processing_started_at IS NOT NULL "
        "AND processing_expires_at IS NOT NULL "
        "AND processing_lease_hash IS NOT NULL) "
        "OR (status = 'consumed' AND consumed_at IS NOT NULL "
        "AND processing_started_at IS NULL "
        "AND processing_expires_at IS NULL "
        "AND processing_lease_hash IS NULL)",
    )
    op.alter_column("embedded_signup_attempts", "status", server_default=None)


def downgrade() -> None:
    op.drop_constraint(
        "ck_embedded_signup_attempt_lifecycle",
        "embedded_signup_attempts",
        type_="check",
    )
    op.drop_index(
        "ix_embedded_signup_attempts_processing_expires_at",
        table_name="embedded_signup_attempts",
    )
    op.drop_column("embedded_signup_attempts", "processing_lease_hash")
    op.drop_column("embedded_signup_attempts", "processing_expires_at")
    op.drop_column("embedded_signup_attempts", "processing_started_at")
    op.drop_column("embedded_signup_attempts", "status")
