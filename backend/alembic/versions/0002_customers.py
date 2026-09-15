"""Customers and appointment ownership, preserving day-one intervals."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("business_id", sa.Integer, sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("phone", sa.String(30), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("business_id", "phone", name="uq_customer_business_phone"),
    )
    op.add_column("appointments", sa.Column("customer_id", sa.Integer, nullable=True))
    op.create_foreign_key("fk_appointment_customer", "appointments", "customers", ["customer_id"], ["id"])


def downgrade():
    op.drop_constraint("fk_appointment_customer", "appointments", type_="foreignkey")
    op.drop_column("appointments", "customer_id")
    op.drop_table("customers")
