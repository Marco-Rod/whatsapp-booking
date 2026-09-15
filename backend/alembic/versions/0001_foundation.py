"""Day one foundation."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade():
    op.create_table("businesses", sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False), sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("phone_number", sa.String(30)), *timestamps())
    op.create_table("services", sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("business_id", sa.Integer, sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False), sa.Column("duration_minutes", sa.Integer, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False), *timestamps(), sa.CheckConstraint("duration_minutes > 0"))
    op.create_index("ix_services_business_id", "services", ["business_id"])
    op.create_table("business_hours", sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("business_id", sa.Integer, sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("weekday", sa.Integer, nullable=False), sa.Column("start_time", sa.Time), sa.Column("end_time", sa.Time),
        sa.Column("is_closed", sa.Boolean, nullable=False), sa.UniqueConstraint("business_id", "weekday"),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6"),
        sa.CheckConstraint("is_closed OR (start_time IS NOT NULL AND end_time IS NOT NULL AND start_time < end_time)"))
    op.create_table("appointments", sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("business_id", sa.Integer, sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("service_id", sa.Integer, sa.ForeignKey("services.id"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("calendar_event_id", sa.String(255)), *timestamps(),
        sa.CheckConstraint("ends_at > starts_at"), sa.CheckConstraint("status IN ('PENDING', 'CONFIRMED', 'CANCELLED', 'COMPLETED')"))
    op.create_index("ix_appointments_availability", "appointments", ["business_id", "starts_at", "ends_at"])


def downgrade():
    for table in ["appointments", "business_hours", "services", "businesses"]:
        op.drop_table(table)
