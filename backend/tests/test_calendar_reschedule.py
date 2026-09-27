from datetime import datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from pydantic import ValidationError

from test_booking import booking_client, create, move
from app.integrations.google_calendar.client import GoogleCalendarClient
from app.integrations.google_calendar.errors import GoogleCalendarError
from app.models import Appointment, GoogleCalendarConnection
from app.services.booking.calendar import BookingCalendarSync
from app.services.booking.booking import BookingConflictError
from app.services.calendar_resolver import CalendarClientResolver, ResolvedCalendar


async def sync_rescheduled(sessions, resolver, appointment_id):
    async with sessions() as session:
        await BookingCalendarSync(session, resolver).rescheduled(appointment_id)


async def sync_created(sessions, resolver, appointment_id):
    async with sessions() as session:
        await BookingCalendarSync(session, resolver).created(appointment_id)


@pytest_asyncio.fixture
async def linked_booking(booking_client):
    _, sessions, _ = booking_client
    original = await create(sessions)
    async with sessions.begin() as session:
        (await session.get(Appointment, original.id)).calendar_event_id = "existing-event"
    google = AsyncMock(spec=GoogleCalendarClient)
    resolver = AsyncMock(spec=CalendarClientResolver)
    resolver.resolve.return_value = ResolvedCalendar(calendar_id="primary", client=google)
    yield sessions, original, google, resolver


async def test_reschedule_commits_before_google_update(linked_booking):
    sessions, original, google, resolver = linked_booking

    async def update(**kwargs):
        async with sessions() as session:
            appointment = await session.get(Appointment, original.id)
            assert appointment.starts_at == datetime.fromisoformat("2026-09-19T15:30:00-06:00")
        assert kwargs["calendar_id"] == "primary"
        assert kwargs["event_id"] == "existing-event"

    google.update_event.side_effect = update
    await move(sessions, original.id)
    await sync_rescheduled(sessions, resolver, original.id)
    google.update_event.assert_awaited_once()


async def test_google_failure_does_not_undo_reschedule(linked_booking):
    sessions, original, google, resolver = linked_booking
    google.update_event.side_effect = GoogleCalendarError("update", status_code=503)
    await move(sessions, original.id)
    await sync_rescheduled(sessions, resolver, original.id)
    google.update_event.assert_awaited_once()
    async with sessions() as session:
        appointment = await session.get(Appointment, original.id)
        assert appointment.starts_at == datetime.fromisoformat("2026-09-19T15:30:00-06:00")
        assert appointment.calendar_event_id == "existing-event"


@pytest.mark.parametrize("kind,start,error", [
    ("conflict", "2026-09-19T15:30:00-06:00", BookingConflictError),
    ("closed", "2026-09-20T15:30:00-06:00", BookingConflictError),
    ("naive", "2026-09-19T15:30:00", ValidationError),
])
async def test_rejected_reschedule_never_calls_google(linked_booking, kind, start, error):
    sessions, original, google, resolver = linked_booking
    if kind == "conflict":
        await create(sessions, starts_at=start)
    with pytest.raises(error):
        await move(sessions, original.id, start)
    google.update_event.assert_not_awaited()
    google.create_event.assert_not_awaited()


async def test_create_uses_oauth_connection(booking_client):
    _, sessions, _ = booking_client
    async with sessions.begin() as session:
        session.add(GoogleCalendarConnection(business_id=1, calendar_id="primary", encrypted_refresh_token="encrypted-token", scopes=["calendar.events"]))
    google = AsyncMock(spec=GoogleCalendarClient)
    google.create_event.return_value = "oauth-event"
    resolver = AsyncMock(spec=CalendarClientResolver)
    resolver.resolve.return_value = ResolvedCalendar(calendar_id="primary", client=google)
    response = await create(sessions)
    await sync_created(sessions, resolver, response.id)
    google.create_event.assert_awaited_once()
    async with sessions() as session:
        assert (await session.get(Appointment, response.id)).calendar_event_id == "oauth-event"


@pytest.mark.parametrize("missing", ["calendar", "event"])
async def test_reschedule_without_calendar_link_still_succeeds(linked_booking, missing):
    sessions, original, google, resolver = linked_booking
    async with sessions.begin() as session:
        if missing == "calendar":
            resolver.resolve.return_value = None
        else:
            (await session.get(Appointment, original.id)).calendar_event_id = None
    await move(sessions, original.id)
    await sync_rescheduled(sessions, resolver, original.id)
    google.update_event.assert_not_awaited()
