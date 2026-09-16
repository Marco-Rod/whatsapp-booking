"""Add optional calendar configuration for businesses.

Appointment.calendar_event_id already exists in revision 0001.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "businesses",
        sa.Column("calendar_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("businesses", "calendar_id")
