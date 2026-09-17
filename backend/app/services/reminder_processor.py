from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Appointment, AppointmentReminder, Business, Customer, Service
from app.services.reminder_sender import ReminderSender, ReminderSendError
from app.services.reminders import ReminderService

logger = logging.getLogger(__name__)
MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def format_reminder(*, service_name: str, starts_at: datetime, business_timezone: str) -> str:
    if starts_at.utcoffset() is None:
        raise ValueError("starts_at must include a timezone")
    local = starts_at.astimezone(ZoneInfo(business_timezone))
    hour = local.hour % 12 or 12
    period = "AM" if local.hour < 12 else "PM"
    return (f"⏰ Recordatorio de tu cita\n\n{service_name}\n"
            f"{local.day} de {MONTHS[local.month - 1]} a las {hour}:{local.minute:02d} {period}.\n\n"
            "Si necesitas hacer un cambio, responde a este mensaje.")


@dataclass(frozen=True)
class ReminderProcessingResult:
    sent: int = 0
    failed: int = 0


class ReminderProcessor:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], sender: ReminderSender):
        self.sessions = sessions
        self.sender = sender

    async def process_due_reminders(self, now: datetime, *, appointment_id: int | None = None) -> int:
        result = await self.process_once(now, appointment_id=appointment_id)
        return result.sent

    async def process_once(self, now: datetime, *, appointment_id: int | None = None) -> ReminderProcessingResult:
        if now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        now = now.astimezone(timezone.utc)
        async with self.sessions() as session:
            due = await ReminderService(session).find_due(now, appointment_id=appointment_id)
        sent = 0
        failed = 0
        for reminder in due:
            token = str(uuid4())
            delivery = await self._claim(reminder.id, token, now)
            if delivery is None:
                continue
            phone, message = delivery
            # No session/transaction is open during this external call.
            try:
                await self.sender.send(phone=phone, message=message)
            except ReminderSendError:
                await self._finish(reminder.id, token, sent_at=None)
                logger.warning("Reminder %s was not acknowledged; remains pending", reminder.id)
                failed += 1
                continue
            # A crash/DB failure here deliberately retains the claim. Do not
            # automatically resend a message whose provider outcome is uncertain.
            await self._finish(reminder.id, token, sent_at=now)
            sent += 1
        return ReminderProcessingResult(sent=sent, failed=failed)

    async def _claim(self, reminder_id: int, token: str, now: datetime) -> tuple[str, str] | None:
        async with self.sessions.begin() as session:
            claimed = await session.scalar(
                update(AppointmentReminder).where(
                    AppointmentReminder.id == reminder_id,
                    AppointmentReminder.sent_at.is_(None),
                    AppointmentReminder.claim_token.is_(None),
                ).values(claim_token=token).returning(AppointmentReminder.id)
            )
            if claimed is None:
                return None
            reminder = await session.get(AppointmentReminder, reminder_id)
            appointment = await session.get(Appointment, reminder.appointment_id)
            if (appointment is None or appointment.status != "CONFIRMED"
                or not now < appointment.starts_at <= now + timedelta(hours=24)
                or reminder.scheduled_for != appointment.starts_at - timedelta(hours=24)):
                reminder.claim_token = None
                return None
            customer = await session.get(Customer, appointment.customer_id) if appointment.customer_id else None
            business = await session.get(Business, appointment.business_id)
            service = await session.get(Service, appointment.service_id)
            if (customer is None or business is None or service is None
                or customer.business_id != business.id or service.business_id != business.id):
                reminder.claim_token = None
                return None
            return customer.phone, format_reminder(
                service_name=service.name, starts_at=appointment.starts_at, business_timezone=business.timezone,
            )

    async def _finish(self, reminder_id: int, token: str, *, sent_at: datetime | None) -> None:
        async with self.sessions.begin() as session:
            owned = await session.scalar(update(AppointmentReminder).where(
                AppointmentReminder.id == reminder_id,
                AppointmentReminder.claim_token == token,
                AppointmentReminder.sent_at.is_(None),
            ).values(sent_at=sent_at, claim_token=None).returning(AppointmentReminder.id))
            if owned is None:
                raise RuntimeError("Reminder claim ownership was lost")
