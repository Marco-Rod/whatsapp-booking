"""Add hashed business administration tokens."""

from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "businesses",
        sa.Column(
            "admin_token_hash",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_businesses_admin_token_hash",
        "businesses",
        ["admin_token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_businesses_admin_token_hash",
        table_name="businesses",
    )
    op.drop_column("businesses", "admin_token_hash")
