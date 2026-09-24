from datetime import datetime
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from test_booking import booking_client, create, move
from app.api.v1.appointments import get_calendar_resolver
from app.core.database import get_session
from app.integrations.google_calendar.client import GoogleCalendarClient
from app.integrations.google_calendar.errors import GoogleCalendarError
from app.main import app
from app.models import Appointment, Business, GoogleCalendarConnection
from app.services.calendar import CalendarService
from app.services.calendar_resolver import CalendarClientResolver, ResolvedCalendar


@pytest_asyncio.fixture
async def linked_booking(booking_client):
    client, sessions, _ = booking_client
    original = (await create(client)).json()
    async with sessions.begin() as session:
        (await session.get(Appointment, original["id"])).calendar_event_id = "existing-event"
    google = AsyncMock(spec=GoogleCalendarClient)
    google.create_event.return_value = "created-event"
    resolver = AsyncMock(spec=CalendarClientResolver)
    resolver.resolve.return_value = ResolvedCalendar(
        calendar_id="primary",
        client=google,
    )
    active = {}
    active["resolver"] = resolver

    async def get_test_session():
        async with sessions() as session:
            active["session"] = session
            yield session

    app.dependency_overrides[get_session] = get_test_session
    app.dependency_overrides[get_calendar_resolver] = lambda: resolver
    try:
        yield client, sessions, original, google, active
    finally:
        app.dependency_overrides.pop(get_calendar_resolver, None)


async def test_reschedule_commits_before_google_update(linked_booking):
    client, sessions, original, google, active = linked_booking

    async def update(**kwargs):
        assert not active["session"].in_transaction()
        async with sessions() as session:
            appointment = await session.get(Appointment, original["id"])
            assert appointment.starts_at == datetime.fromisoformat("2026-09-19T15:30:00-06:00")
            assert appointment.calendar_event_id == "existing-event"
        assert kwargs["calendar_id"] == "primary"
        assert kwargs["event_id"] == "existing-event"
        assert kwargs["event"]["start"]["dateTime"] == "2026-09-19T15:30:00-06:00"
        assert kwargs["event"]["end"]["dateTime"] == "2026-09-19T16:30:00-06:00"

    google.update_event.side_effect = update
    response = await move(client, original["id"])
    assert response.status_code == 200
    google.update_event.assert_awaited_once()
    google.create_event.assert_not_awaited()
    google.delete_event.assert_not_awaited()


async def test_google_failure_does_not_undo_reschedule(linked_booking):
    client, sessions, original, google, _ = linked_booking
    google.update_event.side_effect = GoogleCalendarError("update", status_code=503)
    response = await move(client, original["id"])
    assert response.status_code == 200
    google.update_event.assert_awaited_once()
    google.create_event.assert_not_awaited()
    async with sessions() as session:
        appointment = await session.get(Appointment, original["id"])
        assert appointment.starts_at == datetime.fromisoformat("2026-09-19T15:30:00-06:00")
        assert appointment.ends_at == datetime.fromisoformat("2026-09-19T16:30:00-06:00")
        assert appointment.status == "CONFIRMED"
        assert appointment.calendar_event_id == "existing-event"


@pytest.mark.parametrize("kind,status", [("conflict", 409), ("closed", 409), ("naive", 422)])
async def test_rejected_reschedule_never_calls_google(linked_booking, kind, status):
    client, sessions, original, google, _ = linked_booking
    start = "2026-09-19T15:30:00-06:00"
    if kind == "conflict":
        assert (await create(client, starts_at=start)).status_code == 201
        google.reset_mock()
    elif kind == "closed":
        start = "2026-09-20T15:30:00-06:00"
    else:
        start = "2026-09-19T15:30:00"
    assert (await move(client, original["id"], start)).status_code == status
    google.update_event.assert_not_awaited()
    google.create_event.assert_not_awaited()
    async with sessions() as session:
        appointment = await session.get(Appointment, original["id"])
        assert appointment.starts_at == datetime.fromisoformat(original["starts_at"])
        assert appointment.ends_at == datetime.fromisoformat(original["ends_at"])
        assert appointment.calendar_event_id == "existing-event"


async def test_create_uses_oauth_connection(
    booking_client,
):
    client, sessions, _ = booking_client
    async with sessions.begin() as session:
        session.add(
            GoogleCalendarConnection(
                business_id=1,
                calendar_id="primary",
                encrypted_refresh_token="encrypted-token",
                scopes=["calendar.events"],
            )
        )

    google = AsyncMock(spec=GoogleCalendarClient)
    google.create_event.return_value = "oauth-event"
    resolver = AsyncMock(spec=CalendarClientResolver)
    resolver.resolve.return_value = ResolvedCalendar(
        calendar_id="primary",
        client=google,
    )
    app.dependency_overrides[get_calendar_resolver] = lambda: resolver
    try:
        response = await create(client)
    finally:
        app.dependency_overrides.pop(get_calendar_resolver, None)

    assert response.status_code == 201
    resolver.resolve.assert_awaited_once_with(1)
    google.create_event.assert_awaited_once()
    assert google.create_event.await_args.kwargs["calendar_id"] == "primary"

    async with sessions() as session:
        appointment = await session.get(Appointment, response.json()["id"])
        assert appointment.calendar_event_id == "oauth-event"


@pytest.mark.parametrize("missing", ["calendar", "event"])
async def test_reschedule_without_calendar_link_still_succeeds(linked_booking, missing):
    client, sessions, original, google, _ = linked_booking
    async with sessions.begin() as session:
        if missing == "calendar":
            linked_booking[4]["resolver"].resolve.return_value = None
        else:
            (await session.get(Appointment, original["id"])).calendar_event_id = None
    assert (await move(client, original["id"])).status_code == 200
    google.update_event.assert_not_awaited()
    google.create_event.assert_not_awaited()
