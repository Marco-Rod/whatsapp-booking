from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, AppointmentReminder, Customer

REMINDER_LEAD_TIME = timedelta(hours=24)
REMINDER_DELIVERY_WINDOW = timedelta(minutes=10)


class ReminderService:
    """Discover and materialize due reminders; does not send or claim messages.

    New reminders are materialized only during the delivery window beginning at
    starts_at - REMINDER_LEAD_TIME. Existing pending reminders remain eligible
    after that window so acknowledged delivery failures can be retried.
    A reschedule has a new (appointment_id, starts_at - 24h) key; old records
    remain as history and are not returned for the appointment's new schedule.
    Unclaimed pending records can be returned repeatedly until sent_at is set. The unique
    constraint prevents duplicate records, not duplicate delivery by workers.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_due(self, now: datetime, *, appointment_id: int | None = None) -> list[AppointmentReminder]:
        if now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        now = now.astimezone(timezone.utc)
        dialect = self.session.get_bind().dialect.name
        insert = {"postgresql": pg_insert, "sqlite": sqlite_insert}[dialect]
        due = []
        async with self.session.begin():
            query = select(Appointment).where(
                Appointment.status == "CONFIRMED", Appointment.starts_at > now,
                Appointment.starts_at <= now + REMINDER_LEAD_TIME,
                Appointment.starts_at > (
                    now
                    + REMINDER_LEAD_TIME
                    - REMINDER_DELIVERY_WINDOW
                ),
                # Demo identities are fixtures, never reminder recipients.
                ~select(Customer.id).where(Customer.id == Appointment.customer_id,
                                           Customer.phone.like("demo:%")).exists(),
            )
            if appointment_id is not None:
                query = query.where(Appointment.id == appointment_id)
            appointments = (await self.session.scalars(
                query.order_by(Appointment.starts_at, Appointment.id)
            )).all()
            for appointment in appointments:
                scheduled_for = (
                    appointment.starts_at - REMINDER_LEAD_TIME
                )
                await self.session.execute(
                    insert(AppointmentReminder).values(
                        appointment_id=appointment.id, scheduled_for=scheduled_for,
                    ).on_conflict_do_nothing(index_elements=["appointment_id", "scheduled_for"])
                )

            pending_query = (
                select(AppointmentReminder, Appointment.starts_at)
                .join(
                    Appointment,
                    Appointment.id
                    == AppointmentReminder.appointment_id,
                )
                .where(
                    Appointment.status == "CONFIRMED",
                    Appointment.starts_at > now,
                    AppointmentReminder.sent_at.is_(None),
                    AppointmentReminder.claim_token.is_(None),
                    ~select(Customer.id).where(
                        Customer.id == Appointment.customer_id,
                        Customer.phone.like("demo:%"),
                    ).exists(),
                )
            )
            if appointment_id is not None:
                pending_query = pending_query.where(
                    Appointment.id == appointment_id
                )

            rows = (
                await self.session.execute(
                    pending_query.order_by(
                        AppointmentReminder.scheduled_for,
                        AppointmentReminder.id,
                    ).execution_options(populate_existing=True)
                )
            ).all()

            for reminder, starts_at in rows:
                if reminder.scheduled_for != (
                    starts_at - REMINDER_LEAD_TIME
                ):
                    continue
                self.session.expunge(reminder)
                due.append(reminder)
        return due
