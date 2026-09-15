from datetime import datetime, time
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Time, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from app.models.types import UTCDateTime


class Base(DeclarativeBase):
    pass


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Business(Timestamps, Base):
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(100), default="America/Mexico_City")
    phone_number: Mapped[str | None] = mapped_column(String(30))
    customers: Mapped[list["Customer"]] = relationship(back_populates="business")


class Customer(Timestamps, Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("business_id", "phone", name="uq_customer_business_phone"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    phone: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    business: Mapped["Business"] = relationship(back_populates="customers")
    appointments: Mapped[list["Appointment"]] = relationship(back_populates="customer")


class Service(Timestamps, Base):
    __tablename__ = "services"
    __table_args__ = (CheckConstraint("duration_minutes > 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BusinessHours(Base):
    __tablename__ = "business_hours"
    __table_args__ = (
        UniqueConstraint("business_id", "weekday"),
        CheckConstraint("weekday >= 0 AND weekday <= 6"),
        CheckConstraint("is_closed OR (start_time IS NOT NULL AND end_time IS NOT NULL AND start_time < end_time)"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    weekday: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)


class Appointment(Timestamps, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at"),
        CheckConstraint("status IN ('PENDING', 'CONFIRMED', 'CANCELLED', 'COMPLETED')"),
        Index("ix_appointments_availability", "business_id", "starts_at", "ends_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    calendar_event_id: Mapped[str | None] = mapped_column(String(255))
    # Day-one intervals have no customer; all new bookings require one in the service.
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    customer: Mapped[Customer | None] = relationship(back_populates="appointments")


class Conversation(Timestamps, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("business_id", "phone", name="uq_conversation_business_phone"),
        CheckConstraint("state IN ('main_menu', 'select_service', 'select_date', 'select_time', 'confirm_appointment')", name="ck_conversation_state"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    phone: Mapped[str] = mapped_column(String(30))
    state: Mapped[str] = mapped_column(String(30), default="main_menu")
    context: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), default=dict)


class InboundMessage(Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (UniqueConstraint("business_id", "external_message_id", name="uq_inbound_business_external"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"))
    external_message_id: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
