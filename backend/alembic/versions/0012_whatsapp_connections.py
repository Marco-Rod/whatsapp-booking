"""Add one encrypted WhatsApp connection per business."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "business_id",
            sa.Integer(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("waba_id", sa.String(length=255), nullable=False),
        sa.Column(
            "phone_number_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "display_phone_number",
            sa.String(length=30),
            nullable=True,
        ),
        sa.Column("encrypted_access_token", sa.String(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_scopes", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'connected', 'disconnected', 'error')",
            name="ck_whatsapp_connection_status",
        ),
        sa.UniqueConstraint(
            "business_id",
            name="uq_whatsapp_connection_business",
        ),
        sa.UniqueConstraint(
            "phone_number_id",
            name="uq_whatsapp_connection_phone_number_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("whatsapp_connections")
