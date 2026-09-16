import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.google_calendar.errors import GoogleCalendarError
from app.models import Appointment, Business, Customer, Service
from app.services.calendar import CalendarService

logger = logging.getLogger(__name__)


class BookingCalendarSync:
    """Best-effort synchronization after a successful booking transaction."""

    def __init__(self, session: AsyncSession, calendar: CalendarService):
        self.session = session
        self.calendar = calendar

    async def cancelled(self, appointment_id: int) -> None:
        """Called only for a committed CONFIRMED -> CANCELLED transition."""
        if self.session.in_transaction():
            raise RuntimeError("Calendar synchronization requires a committed booking")
        try:
            async with self.session.begin():
                appointment = await self.session.get(Appointment, appointment_id)
                if appointment is None or appointment.status != "CANCELLED" or not appointment.calendar_event_id:
                    return
                business = await self.session.get(Business, appointment.business_id)
                if business is None or not business.calendar_id:
                    return
                self.session.expunge(appointment)
                self.session.expunge(business)
            await self.calendar.sync_cancelled_appointment(appointment=appointment, business=business)
        except (GoogleCalendarError, SQLAlchemyError, ValueError, LookupError) as exc:
            logger.warning("Calendar cancellation synchronization failed for appointment %s (%s)",
                           appointment_id, type(exc).__name__)

    async def rescheduled(self, appointment_id: int) -> None:
        if self.session.in_transaction():
            raise RuntimeError("Calendar synchronization requires a committed booking")
        try:
            async with self.session.begin():
                appointment = await self.session.get(Appointment, appointment_id)
                if appointment is None or not appointment.calendar_event_id or appointment.status != "CONFIRMED":
                    return
                business = await self.session.get(Business, appointment.business_id)
                if business is None or not business.calendar_id:
                    return
                service = await self.session.get(Service, appointment.service_id)
                customer = await self.session.get(Customer, appointment.customer_id) if appointment.customer_id else None
                if service is None or customer is None:
                    return
                # Detach fully loaded scalars so commit cannot expire them and
                # trigger an implicit read transaction during the external call.
                for obj in (appointment, business, service, customer):
                    self.session.expunge(obj)
            await self.calendar.sync_rescheduled_appointment(
                appointment=appointment, business=business, service=service, customer=customer,
            )
        except (GoogleCalendarError, SQLAlchemyError, ValueError, LookupError) as exc:
            logger.warning("Calendar reschedule synchronization failed for appointment %s (%s)",
                           appointment_id, type(exc).__name__)
