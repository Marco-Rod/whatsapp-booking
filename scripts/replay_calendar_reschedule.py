"""Real RESCHEDULE E2E through the local ASGI endpoint, PostgreSQL and Google.

From backend: python ../scripts/replay_calendar_reschedule.py
Moves test appointment #3 to September 18, 2026 at 16:00 Mexico City time.
Leaves the moved booking and event in place. Does not send WhatsApp messages.
"""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import Session, engine
from app.integrations.google_calendar.factory import calendar_client_from_token
from app.main import app
from app.models import Appointment, Business, Customer

APPOINTMENT_ID = 3
NEW_START = "2026-09-18T16:00:00-06:00"


async def run():
    async with Session() as session:
        appointment = await session.get(Appointment, APPOINTMENT_ID)
        assert appointment is not None and appointment.status == "CONFIRMED"
        business = await session.get(Business, appointment.business_id)
        customer = await session.get(Customer, appointment.customer_id)
        assert business.name == "Bella Studio" and business.calendar_id == "primary"
        assert customer.phone == "+15555550199", "Expected the CREATE replay test customer"
        event_id = appointment.calendar_event_id
        assert event_id, "Appointment must already be linked to an event"
        old_start = appointment.starts_at
        old_end = appointment.ends_at

    google = calendar_client_from_token(settings.google_calendar_token_file)

    def read_event():
        with google._service_factory() as service:
            return service.events().get(calendarId="primary", eventId=event_id).execute(num_retries=0)

    before = await asyncio.to_thread(read_event)
    assert datetime.fromisoformat(before["start"]["dateTime"]) == old_start
    assert datetime.fromisoformat(before["end"]["dateTime"]) == old_end

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://local-e2e") as client:
        response = await client.post(f"/api/v1/appointments/{APPOINTMENT_ID}/reschedule",
                                     json={"starts_at": NEW_START})
        response.raise_for_status()
        assert response.json()["starts_at"] == NEW_START

    async with Session() as session:
        appointment = await session.get(Appointment, APPOINTMENT_ID)
        assert appointment.status == "CONFIRMED"
        assert appointment.calendar_event_id == event_id
        assert appointment.starts_at == datetime.fromisoformat(NEW_START)
        assert appointment.ends_at == datetime.fromisoformat(NEW_START) + timedelta(hours=1)
        new_start, new_end = appointment.starts_at, appointment.ends_at

    after = await asyncio.to_thread(read_event)
    assert before["id"] == after["id"] == event_id
    assert datetime.fromisoformat(after["start"]["dateTime"]) == new_start
    assert datetime.fromisoformat(after["end"]["dateTime"]) == new_end
    print("RESCHEDULE E2E OK: REST endpoint + PostgreSQL + Google Calendar")
    print("Appointment:", APPOINTMENT_ID, "CONFIRMED")
    print("Before:", before["start"]["dateTime"], before["end"]["dateTime"])
    print("After:", after["start"]["dateTime"], after["end"]["dateTime"])
    print("Same calendar_event_id before/after in DB and Google: yes")


async def main():
    try:
        await run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
