"""Add Google Calendar connections per business."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_calendar_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "business_id",
            sa.Integer(),
            sa.ForeignKey("businesses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("calendar_id", sa.String(255), nullable=False),
        sa.Column("account_email", sa.String(320), nullable=True),
        sa.Column("encrypted_refresh_token", sa.String(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), nullable=False),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
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
        sa.UniqueConstraint(
            "business_id",
            name="uq_google_calendar_connection_business",
        ),
    )


def downgrade() -> None:
    op.drop_table("google_calendar_connections")
