import pytest
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as SyncSession

from test_booking import booking_client  # noqa: F401
from test_calendar_reschedule import linked_booking
from app.integrations.google_calendar.errors import GoogleCalendarError
from app.models import Appointment
from app.services.booking.booking import BookingConflictError, BookingService
from app.services.booking.calendar import BookingCalendarSync


async def cancel_and_sync(sessions, resolver, appointment_id):
    async with sessions() as session:
        result = await BookingService(session).cancel_appointment_with_result(appointment_id)
    if result.was_cancelled_now:
        async with sessions() as session:
            await BookingCalendarSync(session, resolver).cancelled(appointment_id)
    return result.appointment


async def test_cancel_commits_before_delete_and_repeat_does_not_delete(linked_booking):
    sessions, original, google, resolver = linked_booking

    async def delete(**kwargs):
        async with sessions() as session:
            assert (await session.get(Appointment, original.id)).status == "CANCELLED"
        assert kwargs == {"calendar_id": "primary", "event_id": "existing-event"}

    google.delete_event.side_effect = delete
    first = await cancel_and_sync(sessions, resolver, original.id)
    second = await cancel_and_sync(sessions, resolver, original.id)
    assert first == second and second.status == "cancelled"
    google.delete_event.assert_awaited_once()


async def test_failed_google_delete_keeps_cancelled_and_id_without_implicit_retry(linked_booking):
    sessions, original, google, resolver = linked_booking
    google.delete_event.side_effect = GoogleCalendarError("delete", status_code=503)
    await cancel_and_sync(sessions, resolver, original.id)
    await cancel_and_sync(sessions, resolver, original.id)
    google.delete_event.assert_awaited_once()
    async with sessions() as session:
        appointment = await session.get(Appointment, original.id)
        assert appointment.status == "CANCELLED"
        assert appointment.calendar_event_id == "existing-event"


@pytest.mark.parametrize("missing", ["calendar", "event"])
async def test_cancel_without_calendar_or_event(linked_booking, missing):
    sessions, original, google, resolver = linked_booking
    async with sessions.begin() as session:
        if missing == "calendar":
            resolver.resolve.return_value = None
        else:
            (await session.get(Appointment, original.id)).calendar_event_id = None
    await cancel_and_sync(sessions, resolver, original.id)
    google.delete_event.assert_not_awaited()


@pytest.mark.parametrize("status", ["PENDING", "COMPLETED"])
async def test_rejected_cancel_never_deletes_event(linked_booking, status):
    sessions, original, google, resolver = linked_booking
    async with sessions.begin() as session:
        (await session.get(Appointment, original.id)).status = status
    with pytest.raises(BookingConflictError):
        await cancel_and_sync(sessions, resolver, original.id)
    google.delete_event.assert_not_awaited()


async def test_failed_database_commit_never_deletes_event(linked_booking):
    sessions, original, google, resolver = linked_booking

    def fail_commit(session):
        raise SQLAlchemyError("Simulated database commit rejection")

    event.listen(SyncSession, "before_commit", fail_commit)
    try:
        with pytest.raises(SQLAlchemyError, match="commit rejection"):
            await cancel_and_sync(sessions, resolver, original.id)
    finally:
        event.remove(SyncSession, "before_commit", fail_commit)
    google.delete_event.assert_not_awaited()


async def test_cancellation_result_reports_only_actual_transition(linked_booking):
    sessions, original, _, _ = linked_booking
    async with sessions() as session:
        service = BookingService(session)
        first = await service.cancel_appointment_with_result(original.id)
        assert not session.in_transaction()
        second = await service.cancel_appointment_with_result(original.id)
        assert first.was_cancelled_now is True
        assert second.was_cancelled_now is False
