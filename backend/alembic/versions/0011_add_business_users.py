"""Add external identity users for business administration."""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "display_name",
            sa.String(length=200),
            nullable=True,
        ),
        sa.Column(
            "auth_provider",
            sa.String(length=50),
            nullable=False,
        ),
        sa.Column(
            "provider_subject",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "auth_provider",
            "provider_subject",
            name="uq_business_user_provider_subject",
        ),
    )
    op.create_index(
        "ix_business_users_business_id",
        "business_users",
        ["business_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_business_users_business_id",
        table_name="business_users",
    )
    op.drop_table("business_users")
