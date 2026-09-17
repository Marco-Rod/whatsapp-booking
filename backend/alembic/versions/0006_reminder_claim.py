"""Add an atomic ownership token for reminder delivery."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("appointment_reminders", sa.Column("claim_token", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("appointment_reminders", "claim_token")
