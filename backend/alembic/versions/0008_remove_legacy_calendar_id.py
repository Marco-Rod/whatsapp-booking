"""Remove the legacy business calendar identifier."""

from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("businesses", "calendar_id")


def downgrade() -> None:
    op.add_column(
        "businesses",
        sa.Column(
            "calendar_id",
            sa.String(length=255),
            nullable=True,
        ),
    )
