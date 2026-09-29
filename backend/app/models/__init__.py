from datetime import datetime, time
from enum import Enum
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
    admin_token_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    customers: Mapped[list["Customer"]] = relationship(back_populates="business")
    users: Mapped[list["BusinessUser"]] = relationship(
        back_populates="business",
        cascade="all, delete-orphan",
    )
    google_calendar_connection: Mapped["GoogleCalendarConnection | None"] = relationship(
        back_populates="business",
        uselist=False,
        cascade="all, delete-orphan",
    )
    whatsapp_connection: Mapped["WhatsAppConnection | None"] = relationship(
        back_populates="business",
        uselist=False,
        cascade="all, delete-orphan",
    )


class BusinessUser(Timestamps, Base):
    __tablename__ = "business_users"
    __table_args__ = (
        UniqueConstraint(
            "auth_provider",
            "provider_subject",
            name="uq_business_user_provider_subject",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    auth_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    provider_subject: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    business: Mapped["Business"] = relationship(
        back_populates="users",
    )


class GoogleCalendarConnection(Timestamps, Base):
    __tablename__ = "google_calendar_connections"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            name="uq_google_calendar_connection_business",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )

    calendar_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="primary",
    )

    account_email: Mapped[str | None] = mapped_column(
        String(320),
        nullable=True,
    )

    encrypted_refresh_token: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    scopes: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        default=list,
        nullable=False,
    )

    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    business: Mapped["Business"] = relationship(
        back_populates="google_calendar_connection",
    )


class WhatsAppConnectionStatus(str, Enum):
    PENDING = "pending"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class WhatsAppConnection(Timestamps, Base):
    __tablename__ = "whatsapp_connections"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            name="uq_whatsapp_connection_business",
        ),
        UniqueConstraint(
            "phone_number_id",
            name="uq_whatsapp_connection_phone_number_id",
        ),
        CheckConstraint(
            "status IN ('pending', 'connected', 'disconnected', 'error')",
            name="ck_whatsapp_connection_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
    )
    waba_id: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    display_phone_number: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )
    encrypted_access_token: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    granted_scopes: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        default=list,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=WhatsAppConnectionStatus.PENDING.value,
        nullable=False,
    )
    connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    disconnected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    business: Mapped["Business"] = relationship(
        back_populates="whatsapp_connection",
    )


class EmbeddedSignupAttemptStatus(str, Enum):
    READY = "ready"
    PROCESSING = "processing"
    CONSUMED = "consumed"


class EmbeddedSignupAttempt(Base):
    """A single-use application correlation nonce for Meta Embedded Signup."""

    __tablename__ = "embedded_signup_attempts"
    __table_args__ = (
        Index("ix_embedded_signup_attempts_expires_at", "expires_at"),
        Index(
            "ix_embedded_signup_attempts_processing_expires_at",
            "status",
            "processing_expires_at",
        ),
        CheckConstraint(
            "(status = 'ready' AND consumed_at IS NULL "
            "AND processing_started_at IS NULL "
            "AND processing_expires_at IS NULL "
            "AND processing_lease_hash IS NULL) "
            "OR (status = 'processing' AND consumed_at IS NULL "
            "AND processing_started_at IS NOT NULL "
            "AND processing_expires_at IS NOT NULL "
            "AND processing_lease_hash IS NOT NULL) "
            "OR (status = 'consumed' AND consumed_at IS NOT NULL "
            "AND processing_started_at IS NULL "
            "AND processing_expires_at IS NULL "
            "AND processing_lease_hash IS NULL)",
            name="ck_embedded_signup_attempt_lifecycle",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nonce_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=EmbeddedSignupAttemptStatus.READY.value,
        nullable=False,
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processing_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processing_lease_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )


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
    calendar_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Day-one intervals have no customer; all new bookings require one in the service.
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    customer: Mapped[Customer | None] = relationship(back_populates="appointments")


class AppointmentReminder(Timestamps, Base):
    __tablename__ = "appointment_reminders"
    __table_args__ = (
        UniqueConstraint("appointment_id", "scheduled_for", name="uq_appointment_reminder_schedule"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)


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
