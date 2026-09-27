from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Appointment, Base, Business, BusinessHours, Service
from app.repositories.availability import AvailabilityRepository
from app.services.booking.availability import (
    AvailabilityService,
    NotFoundError,
    generate_slots,
)

ZONE = ZoneInfo("America/Mexico_City")


def dt(hour, minute=0):
    return datetime(2026, 9, 19, hour, minute, tzinfo=ZONE)


@pytest.mark.parametrize(
    "duration,count,last",
    [(30, 18, "17:30"), (45, 17, "17:00"), (60, 17, "17:00"),
     (120, 15, "16:00"), (600, 0, None)],
)
def test_durations(duration, count, last):
    slots = generate_slots(dt(9), dt(18), duration, 30, [])
    assert len(slots) == count
    if last:
        assert slots[-1].starts_at.strftime("%H:%M") == last


@pytest.mark.parametrize("start,end,allowed", [
    (dt(10), dt(11), False), (dt(9, 30), dt(10, 30), False),
    (dt(10, 30), dt(11, 30), False), (dt(9), dt(12), False),
    (dt(10, 15), dt(10, 45), False), (dt(9), dt(10), True),
    (dt(11), dt(12), True),
])
def test_overlap(start, end, allowed):
    slots = generate_slots(dt(10), dt(11), 60, 30, [(start, end)])
    assert bool(slots) is allowed


@pytest_asyncio.fixture
async def availability_sessions():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        session.add_all([
            Business(id=1, name="Demo", timezone=str(ZONE)),
            Business(id=2, name="Other", timezone=str(ZONE)),
            Service(id=1, business_id=1, name="Corte", duration_minutes=60),
            Service(id=2, business_id=2, name="Other", duration_minutes=60),
            Service(
                id=3,
                business_id=1,
                name="Inactive",
                duration_minutes=60,
                is_active=False,
            ),
            BusinessHours(
                business_id=1,
                weekday=5,
                start_time=time(9),
                end_time=time(18),
            ),
            BusinessHours(business_id=1, weekday=6, is_closed=True),
        ])
    try:
        yield sessions
    finally:
        await engine.dispose()


async def availability(sessions, **overrides):
    async with sessions() as session:
        return await AvailabilityService(
            AvailabilityRepository(session),
            interval_minutes=30,
        ).get_available_slots(
            overrides.get("business_id", 1),
            overrides.get("service_id", 1),
            overrides.get("date", date(2026, 9, 19)),
        )


async def test_open_day_returns_slots(availability_sessions):
    response = await availability(availability_sessions)
    assert len(response.slots) == 17
    assert response.slots[0].starts_at == dt(9)


@pytest.mark.parametrize("overrides", [
    {"business_id": 99}, {"business_id": 0}, {"service_id": 99},
    {"service_id": 2}, {"service_id": 3},
])
async def test_missing_or_inactive_business_service_is_not_found(
    availability_sessions,
    overrides,
):
    with pytest.raises(NotFoundError):
        await availability(availability_sessions, **overrides)


@pytest.mark.parametrize("day", [date(2026, 9, 20), date(2026, 9, 21)])
async def test_closed_or_missing_hours_return_no_slots(availability_sessions, day):
    response = await availability(availability_sessions, date=day)
    assert response.slots == []


@pytest.mark.parametrize("status,count", [
    ("CANCELLED", 17), ("COMPLETED", 17), ("PENDING", 14), ("CONFIRMED", 14),
])
async def test_appointment_status_affects_availability(
    availability_sessions,
    status,
    count,
):
    async with availability_sessions.begin() as session:
        session.add(Appointment(
            business_id=1,
            service_id=1,
            starts_at=dt(10).astimezone(timezone.utc),
            ends_at=dt(11).astimezone(timezone.utc),
            status=status,
        ))
    response = await availability(availability_sessions)
    assert len(response.slots) == count
