import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from test_booking import booking_client
from app.models import Appointment, AppointmentReminder
from app.services.reminders import ReminderService

NOW = datetime(2026, 9, 17, 22, tzinfo=timezone.utc)


async def add_appointment(
    sessions,
    *,
    start=None,
    status="CONFIRMED",
    booked_at=None,
):
    start = start or NOW + timedelta(hours=24)
    async with sessions.begin() as session:
        values = {}
        if booked_at is not None:
            values["created_at"] = booked_at
        appointment = Appointment(
            business_id=1,
            service_id=1,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            status=status,
            **values,
        )
        session.add(appointment)
        await session.flush()
        return appointment.id


async def find(sessions, now=NOW):
    async with sessions() as session:
        return await ReminderService(session).find_due(now)


async def test_confirmed_due_reminder_is_created_in_utc(booking_client):
    _, sessions, _ = booking_client
    appointment_id = await add_appointment(sessions)
    due = await find(sessions, NOW.astimezone(ZoneInfo("America/Mexico_City")))
    assert len(due) == 1
    assert due[0].appointment_id == appointment_id
    assert due[0].scheduled_for == NOW
    assert due[0].scheduled_for.utcoffset() == timedelta(0)
    assert due[0].sent_at is None


@pytest.mark.parametrize(
    "lead_time",
    [timedelta(days=10), timedelta(hours=25)],
    ids=["ten-days-before", "twenty-five-hours-before"],
)
async def test_reminder_is_not_due_before_target_time(
    booking_client,
    lead_time,
):
    _, sessions, _ = booking_client
    await add_appointment(
        sessions,
        start=NOW + lead_time,
        booked_at=NOW,
    )

    assert await find(sessions) == []


async def test_late_booking_is_not_due_immediately(booking_client):
    """Regression: a 17:27 booking for tomorrow 09:00 is not due at 17:30."""
    _, sessions, _ = booking_client
    cron_time = datetime(2026, 9, 17, 23, 30, tzinfo=timezone.utc)
    await add_appointment(
        sessions,
        booked_at=cron_time - timedelta(minutes=3),
        start=datetime(2026, 9, 18, 15, 0, tzinfo=timezone.utc),
    )

    assert await find(sessions, cron_time) == []


@pytest.mark.parametrize(
    "lead_time",
    [timedelta(hours=2), timedelta(minutes=20)],
    ids=["two-hours-before", "twenty-minutes-before"],
)
async def test_very_late_booking_has_no_immediate_reminder(
    booking_client,
    lead_time,
):
    _, sessions, _ = booking_client
    await add_appointment(
        sessions,
        booked_at=NOW - timedelta(minutes=3),
        start=NOW + lead_time,
    )

    assert await find(sessions) == []


@pytest.mark.parametrize("status", ["CANCELLED", "PENDING", "COMPLETED"])
async def test_non_confirmed_is_ignored(booking_client, status):
    _, sessions, _ = booking_client
    await add_appointment(sessions, status=status)
    assert await find(sessions) == []


@pytest.mark.parametrize("offset", [timedelta(hours=24, microseconds=1), timedelta(0), timedelta(hours=-1)])
async def test_outside_window_is_ignored(booking_client, offset):
    _, sessions, _ = booking_client
    await add_appointment(sessions, start=NOW + offset)
    assert await find(sessions) == []


@pytest.mark.parametrize(
    "delay",
    [
        timedelta(0),
        timedelta(minutes=5),
        timedelta(minutes=9, seconds=59),
    ],
    ids=["exact-target", "five-minutes", "nine-minutes-fifty-nine"],
)
async def test_reminder_is_created_within_delivery_window(
    booking_client,
    delay,
):
    _, sessions, _ = booking_client
    await add_appointment(sessions)
    due = await find(sessions, NOW + delay)
    assert len(due) == 1 and due[0].scheduled_for == NOW


async def test_new_reminder_is_not_created_at_window_end(booking_client):
    _, sessions, _ = booking_client
    await add_appointment(sessions)

    assert await find(sessions, NOW + timedelta(minutes=10)) == []


async def test_pending_reminder_remains_due_after_delivery_window(
    booking_client,
):
    _, sessions, _ = booking_client
    await add_appointment(sessions)
    first = await find(sessions)

    retried = await find(sessions, NOW + timedelta(minutes=11))

    assert [reminder.id for reminder in retried] == [first[0].id]


async def test_repeated_runs_reuse_record_and_sent_is_excluded(booking_client):
    _, sessions, _ = booking_client
    await add_appointment(sessions)
    first = await find(sessions)
    second = await find(sessions)
    assert [r.id for r in first] == [r.id for r in second]
    async with sessions.begin() as session:
        (await session.get(AppointmentReminder, first[0].id)).sent_at = NOW
    assert await find(sessions) == []
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AppointmentReminder)) == 1


async def test_reschedule_ignores_old_schedule_and_preserves_history(booking_client):
    _, sessions, _ = booking_client
    appointment_id = await add_appointment(sessions)
    old = (await find(sessions))[0]
    async with sessions.begin() as session:
        appointment = await session.get(Appointment, appointment_id)
        appointment.starts_at += timedelta(hours=2)
        appointment.ends_at += timedelta(hours=2)
        (await session.get(AppointmentReminder, old.id)).sent_at = NOW
    assert await find(sessions) == []
    new = (await find(sessions, NOW + timedelta(hours=2)))[0]
    assert new.id != old.id and new.scheduled_for == NOW + timedelta(hours=2)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AppointmentReminder)) == 2


async def test_cancelled_existing_pending_reminder_is_not_returned(booking_client):
    _, sessions, _ = booking_client
    appointment_id = await add_appointment(sessions)
    await find(sessions)
    async with sessions.begin() as session:
        (await session.get(Appointment, appointment_id)).status = "CANCELLED"
    assert await find(sessions) == []


async def test_naive_now_is_rejected(booking_client):
    _, sessions, _ = booking_client
    with pytest.raises(ValueError, match="timezone"):
        await find(sessions, NOW.replace(tzinfo=None))


async def test_concurrent_discovery_postgresql(booking_client):
    _, sessions, postgres = booking_client
    if not postgres:
        pytest.skip("Requires PostgreSQL for concurrent upsert verification")
    await add_appointment(sessions)
    results = await asyncio.gather(find(sessions), find(sessions))
    assert results[0][0].id == results[1][0].id
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AppointmentReminder)) == 1
