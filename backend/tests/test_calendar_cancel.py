import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as SyncSession

from test_booking import booking_client
from test_calendar_reschedule import linked_booking
from app.integrations.google_calendar.errors import GoogleCalendarError
from app.models import Appointment, Business
from app.services.booking.booking import BookingService


async def cancel(client, appointment_id):
    return await client.post(f"/api/v1/appointments/{appointment_id}/cancel")


async def test_cancel_commits_before_delete_and_repeat_does_not_delete(linked_booking):
    client, sessions, original, google, active = linked_booking

    async def delete(**kwargs):
        assert not active["session"].in_transaction()
        async with sessions() as session:
            appointment = await session.get(Appointment, original["id"])
            assert appointment.status == "CANCELLED"
            assert appointment.calendar_event_id == "existing-event"
        assert kwargs == {"calendar_id": "primary", "event_id": "existing-event"}

    google.delete_event.side_effect = delete
    first = await cancel(client, original["id"])
    second = await cancel(client, original["id"])
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    google.delete_event.assert_awaited_once()
    google.create_event.assert_not_awaited()
    google.update_event.assert_not_awaited()
    async with sessions() as session:
        assert (await session.get(Appointment, original["id"])).calendar_event_id == "existing-event"


async def test_failed_google_delete_keeps_cancelled_and_id_without_implicit_retry(linked_booking):
    client, sessions, original, google, _ = linked_booking
    google.delete_event.side_effect = GoogleCalendarError("delete", status_code=503)
    assert (await cancel(client, original["id"])).status_code == 200
    assert (await cancel(client, original["id"])).status_code == 200
    google.delete_event.assert_awaited_once()
    async with sessions() as session:
        appointment = await session.get(Appointment, original["id"])
        assert appointment.status == "CANCELLED"
        assert appointment.calendar_event_id == "existing-event"


@pytest.mark.parametrize("missing", ["calendar", "event"])
async def test_cancel_without_calendar_or_event(linked_booking, missing):
    client, sessions, original, google, active = linked_booking
    async with sessions.begin() as session:
        if missing == "calendar":
            active["resolver"].resolve.return_value = None
        else:
            (await session.get(Appointment, original["id"])).calendar_event_id = None
    assert (await cancel(client, original["id"])).status_code == 200
    google.delete_event.assert_not_awaited()


@pytest.mark.parametrize("status", ["PENDING", "COMPLETED"])
async def test_rejected_cancel_never_deletes_event(linked_booking, status):
    client, sessions, original, google, _ = linked_booking
    async with sessions.begin() as session:
        (await session.get(Appointment, original["id"])).status = status
    assert (await cancel(client, original["id"])).status_code == 409
    google.delete_event.assert_not_awaited()
    async with sessions() as session:
        appointment = await session.get(Appointment, original["id"])
        assert appointment.status == status
        assert appointment.calendar_event_id == "existing-event"


async def test_failed_database_commit_never_deletes_event(linked_booking):
    client, sessions, original, google, _ = linked_booking

    def fail_commit(session):
        raise SQLAlchemyError("Simulated database commit rejection")

    event.listen(SyncSession, "before_commit", fail_commit)
    try:
        with pytest.raises(SQLAlchemyError, match="commit rejection"):
            await cancel(client, original["id"])
    finally:
        event.remove(SyncSession, "before_commit", fail_commit)
    google.delete_event.assert_not_awaited()
    async with sessions() as session:
        appointment = await session.get(Appointment, original["id"])
        assert appointment.status == "CONFIRMED"
        assert appointment.calendar_event_id == "existing-event"


async def test_cancellation_result_reports_only_actual_transition(linked_booking):
    _, sessions, original, _, _ = linked_booking
    async with sessions() as session:
        service = BookingService(session)
        first = await service.cancel_appointment_with_result(original["id"])
        assert not session.in_transaction()
        second = await service.cancel_appointment_with_result(original["id"])
        assert first.was_cancelled_now is True
        assert second.was_cancelled_now is False
        assert first.appointment == second.appointment
        assert await service.cancel_appointment(original["id"]) == first.appointment
