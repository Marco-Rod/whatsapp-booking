from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from app.integrations.google_calendar.client import GoogleCalendarClient

if TYPE_CHECKING:
    from app.models import Appointment, Business, Customer, Service


@dataclass(frozen=True)
class CalendarEventData:
    summary: str
    description: str
    start_at: datetime
    end_at: datetime
    timezone: str

    @classmethod
    def from_appointment(
        cls, *, appointment: "Appointment", business: "Business",
        service: "Service", customer: "Customer",
    ) -> "CalendarEventData":
        """Build event data from loaded domain objects without DB access."""
        name = customer.name if customer.name and customer.name != customer.phone else "Sin nombre"
        return cls(
            summary=f"{service.name} - {business.name}",
            description=f"Cliente: {name}\nReserva creada por WhatsApp Booking",
            start_at=appointment.starts_at,
            end_at=appointment.ends_at,
            timezone=business.timezone,
        )

    def to_payload(self) -> dict[str, Any]:
        if self.start_at.utcoffset() is None or self.end_at.utcoffset() is None:
            raise ValueError("Calendar event dates must be timezone-aware")
        if self.end_at <= self.start_at:
            raise ValueError("Calendar event must end after it starts")
        timezone = ZoneInfo(self.timezone)
        return {
            "summary": self.summary,
            "description": self.description,
            "start": {
                "dateTime": self.start_at.astimezone(timezone).isoformat(),
                "timeZone": self.timezone,
            },
            "end": {
                "dateTime": self.end_at.astimezone(timezone).isoformat(),
                "timeZone": self.timezone,
            },
        }


class CalendarService:
    """Translate domain event data to Calendar operations, without persistence.

    Errors propagate to the caller. Booking orchestration, persistence and
    synchronization/idempotency policy are handled in a later checkpoint.
    """

    def __init__(self, client: GoogleCalendarClient):
        self.client = client

    async def sync_created_appointment(
        self, *, appointment: "Appointment", business: "Business",
        service: "Service", customer: "Customer", calendar_id: str,
    ) -> str | None:
        """Create an event if enabled, without modifying or saving the appointment.

        The caller must invoke this after the booking transaction commits and
        persist the returned ID separately. Integration errors propagate.
        """
        event = CalendarEventData.from_appointment(
            appointment=appointment, business=business,
            service=service, customer=customer,
        )
        return await self.create(calendar_id=calendar_id, event=event)

    async def create(self, *, calendar_id: str, event: CalendarEventData) -> str:
        return await self.client.create_event(
            calendar_id=calendar_id, event=event.to_payload(),
        )

    async def sync_rescheduled_appointment(
        self, *, appointment: "Appointment", business: "Business",
        service: "Service", customer: "Customer", calendar_id: str,
    ) -> None:
        """Update only a linked event; never mutate the appointment or create one."""
        if not appointment.calendar_event_id:
            return
        event = CalendarEventData.from_appointment(
            appointment=appointment, business=business, service=service, customer=customer,
        )
        await self.update(
            calendar_id=calendar_id,
            event_id=appointment.calendar_event_id, event=event,
        )

    async def update(
        self, *, calendar_id: str, event_id: str, event: CalendarEventData,
    ) -> None:
        await self.client.update_event(
            calendar_id=calendar_id, event_id=event_id, event=event.to_payload(),
        )

    async def delete(self, *, calendar_id: str, event_id: str) -> None:
        await self.client.delete_event(calendar_id=calendar_id, event_id=event_id)

    async def sync_cancelled_appointment(
        self, *, appointment: "Appointment", business: "Business",
        calendar_id: str,
    ) -> None:
        """Delete the associated event without clearing its ID on the appointment."""
        if not appointment.calendar_event_id:
            return
        await self.delete(calendar_id=calendar_id, event_id=appointment.calendar_event_id)
