"""Cancel test appointment #3 via REST and verify its real Google event is inactive.

From backend: python ../scripts/replay_calendar_cancel.py
Leaves the appointment CANCELLED with its original calendar_event_id for tracing.
No WhatsApp messages are sent. The first run requires the test booking to be
CONFIRMED; a duplicate cancellation is exercised within that same run.
"""
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from googleapiclient.errors import HttpError
from httpx import ASGITransport, AsyncClient

from app.api.v1.appointments import get_calendar_service
from app.core.config import settings
from app.core.database import Session, engine
from app.integrations.google_calendar.factory import calendar_client_from_token
from app.main import app
from app.models import Appointment, Business, Customer
from app.services.calendar import CalendarService

APPOINTMENT_ID = 3


class ObservedCalendar(CalendarService):
    def __init__(self, client):
        super().__init__(client)
        self.calls = 0

    async def sync_cancelled_appointment(self, **kwargs):
        self.calls += 1
        await super().sync_cancelled_appointment(**kwargs)


async def run():
    async with Session() as session:
        appointment = await session.get(Appointment, APPOINTMENT_ID)
        assert appointment is not None and appointment.status == "CONFIRMED"
        business = await session.get(Business, appointment.business_id)
        customer = await session.get(Customer, appointment.customer_id)
        assert business.name == "Bella Studio" and business.calendar_id == "primary"
        assert customer.phone == "+15555550199", "Expected the lifecycle replay test customer"
        event_id = appointment.calendar_event_id
        assert event_id
        original_times = (appointment.starts_at, appointment.ends_at)

    google = calendar_client_from_token(settings.google_calendar_token_file)

    def read_event():
        with google._service_factory() as service:
            return service.events().get(calendarId="primary", eventId=event_id).execute(num_retries=0)

    before = await asyncio.to_thread(read_event)
    assert before["id"] == event_id and before["status"] != "cancelled"
    calendar = ObservedCalendar(google)
    app.dependency_overrides[get_calendar_service] = lambda: calendar
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://local-e2e") as client:
            first = await client.post(f"/api/v1/appointments/{APPOINTMENT_ID}/cancel")
            first.raise_for_status()
            second = await client.post(f"/api/v1/appointments/{APPOINTMENT_ID}/cancel")
            second.raise_for_status()
            assert first.json() == second.json()
        assert calendar.calls == 1
    finally:
        app.dependency_overrides.pop(get_calendar_service, None)

    async with Session() as session:
        appointment = await session.get(Appointment, APPOINTMENT_ID)
        assert appointment.status == "CANCELLED"
        assert appointment.calendar_event_id == event_id
        assert (appointment.starts_at, appointment.ends_at) == original_times

    try:
        after = await asyncio.to_thread(read_event)
    except HttpError as exc:
        if exc.resp.status not in (404, 410):
            raise
        google_status = f"HTTP {exc.resp.status}"
    else:
        assert after["id"] == event_id and after["status"] == "cancelled"
        google_status = "status=cancelled"

    print("CANCEL E2E OK: REST endpoint + PostgreSQL + Google Calendar")
    print("Appointment:", APPOINTMENT_ID, "CANCELLED")
    print("Original calendar_event_id retained: yes")
    print("Google event is no longer active:", google_status)
    print("Two cancellations, one Calendar synchronization: yes")


async def main():
    try:
        await run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
