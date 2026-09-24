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

from app.api.v1.appointments import get_calendar_resolver
from app.core.database import Session, engine
from app.main import app
from app.models import Appointment, Business, Customer
from app.services.calendar_resolver import CalendarClientResolver, ResolvedCalendar

APPOINTMENT_ID = 3


class ObservedClient:
    def __init__(self, client):
        self.client = client
        self.calls = 0

    async def delete_event(self, *args, **kwargs):
        self.calls += 1
        await self.client.delete_event(*args, **kwargs)


class FixedResolver:
    def __init__(self, resolved):
        self.resolved = resolved

    async def resolve(self, business_id):
        return self.resolved


async def run():
    async with Session() as session:
        appointment = await session.get(Appointment, APPOINTMENT_ID)
        assert appointment is not None and appointment.status == "CONFIRMED"
        business = await session.get(Business, appointment.business_id)
        customer = await session.get(Customer, appointment.customer_id)
        assert business.name == "Bella Studio"
        assert customer.phone == "+15555550199", "Expected the lifecycle replay test customer"
        resolved = await CalendarClientResolver(session).resolve(
            appointment.business_id
        )
        assert resolved is not None, "Business has no Google Calendar connection"
        event_id = appointment.calendar_event_id
        assert event_id
        original_times = (appointment.starts_at, appointment.ends_at)

    google = resolved.client
    observed = ObservedClient(google)
    replay_resolver = FixedResolver(
        ResolvedCalendar(
            calendar_id=resolved.calendar_id,
            client=observed,
        )
    )

    def read_event():
        with google._service_factory() as service:
            return service.events().get(
                calendarId=resolved.calendar_id,
                eventId=event_id,
            ).execute(num_retries=0)

    before = await asyncio.to_thread(read_event)
    assert before["id"] == event_id and before["status"] != "cancelled"
    app.dependency_overrides[get_calendar_resolver] = lambda: replay_resolver
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://local-e2e") as client:
            first = await client.post(f"/api/v1/appointments/{APPOINTMENT_ID}/cancel")
            first.raise_for_status()
            second = await client.post(f"/api/v1/appointments/{APPOINTMENT_ID}/cancel")
            second.raise_for_status()
            assert first.json() == second.json()
        assert observed.calls == 1
    finally:
        app.dependency_overrides.pop(get_calendar_resolver, None)

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
