import asyncio
import os
from datetime import date, time
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import app
from app.models import Appointment, Base, Business, BusinessHours, Customer, Service
from app.schemas.booking import AppointmentCreate, AppointmentReschedule
from app.services.booking.availability import NotFoundError
from app.services.booking.booking import BookingConflictError, BookingService


@pytest_asyncio.fixture
async def booking_client():
    url = os.getenv("TEST_DATABASE_URL", "sqlite+aiosqlite://")
    postgres = url.startswith("postgresql")
    admin = None
    schema = "test_booking_" + uuid4().hex
    if postgres:
        admin = create_async_engine(url)
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            session.add_all([
                Business(id=1, name="One", timezone="America/Mexico_City"),
                Business(id=2, name="Two", timezone="America/Mexico_City"),
            ])
            session.add_all([
                Service(id=1, business_id=1, name="Cut", duration_minutes=60),
                Service(id=2, business_id=2, name="Cut", duration_minutes=60),
                Service(id=3, business_id=1, name="Inactive", duration_minutes=60, is_active=False),
                Service(id=4, business_id=1, name="Long", duration_minutes=120),
            ])
            for business_id in (1, 2):
                session.add(BusinessHours(business_id=business_id, weekday=5, start_time=time(9), end_time=time(18)))
                session.add(BusinessHours(business_id=business_id, weekday=6, is_closed=True))

        async def override():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = override
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, sessions, postgres
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
        if admin:
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()


def payload(**overrides):
    return {
        "business_id": 1,
        "service_id": 1,
        "customer": {"name": "Andrea", "phone": "+523312345678"},
        "starts_at": "2026-09-19T11:30:00-06:00",
        **overrides,
    }


async def create(sessions, **overrides):
    request = AppointmentCreate.model_validate(payload(**overrides))
    async with sessions() as session:
        return await BookingService(session).create_appointment(request)


async def get(sessions, appointment_id):
    async with sessions() as session:
        return await BookingService(session).get_appointment(appointment_id)


async def move(sessions, appointment_id, start="2026-09-19T15:30:00-06:00"):
    request = AppointmentReschedule.model_validate({"starts_at": start})
    async with sessions() as session:
        return await BookingService(session).reschedule_appointment(appointment_id, request)


async def cancel(sessions, appointment_id):
    async with sessions() as session:
        return await BookingService(session).cancel_appointment(appointment_id)


async def available_starts(sessions):
    async with sessions() as session:
        slots = await BookingService(session).availability.get_available_slots(1, 1, date(2026, 9, 19))
        return [slot.starts_at.isoformat() for slot in slots.slots]


async def test_create_persists_and_blocks_availability(booking_client):
    _, sessions, _ = booking_client
    response = await create(sessions)
    assert response.status == "confirmed"
    assert response.ends_at.isoformat() == "2026-09-19T12:30:00-06:00"
    async with sessions() as session:
        appointment = await session.get(Appointment, response.id)
        assert appointment.customer_id == response.customer.id
        assert appointment.status == "CONFIRMED"
    assert response.starts_at.isoformat() not in await available_starts(sessions)


async def test_customer_reuse_and_business_isolation(booking_client):
    _, sessions, _ = booking_client
    first = await create(sessions)
    second = await create(sessions, starts_at="2026-09-19T13:00:00-06:00")
    other = await create(sessions, business_id=2, service_id=2)
    assert first.customer.id == second.customer.id
    assert first.customer.id != other.customer.id
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Customer)) == 2


@pytest.mark.parametrize("overrides,error", [
    ({"business_id": 999}, NotFoundError), ({"service_id": 999}, NotFoundError),
    ({"service_id": 2}, NotFoundError), ({"service_id": 3}, BookingConflictError),
    ({"starts_at": "2026-09-19T08:30:00-06:00"}, BookingConflictError),
    ({"starts_at": "2026-09-20T11:30:00-06:00"}, BookingConflictError),
])
async def test_invalid_create_leaves_no_records(booking_client, overrides, error):
    _, sessions, _ = booking_client
    with pytest.raises(error):
        await create(sessions, **overrides)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Customer)) == 0
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 0


def test_create_schema_rejects_invalid_payloads():
    for overrides in (
        {"starts_at": "2026-09-19T11:30:00"},
        {"customer": {"name": " ", "phone": "+523312345678"}},
        {"customer": {"name": "Andrea", "phone": "3312345678"}},
        {"status": "cancelled"},
    ):
        with pytest.raises(ValidationError):
            AppointmentCreate.model_validate(payload(**overrides))


@pytest.mark.parametrize("hour,raises", [("11:30", True), ("11:00", True), ("12:00", True), ("10:30", False), ("12:30", False)])
async def test_overlap_and_adjacency(booking_client, hour, raises):
    _, sessions, _ = booking_client
    await create(sessions)
    if raises:
        with pytest.raises(BookingConflictError):
            await create(sessions, starts_at=f"2026-09-19T{hour}:00-06:00")
    else:
        await create(sessions, starts_at=f"2026-09-19T{hour}:00-06:00")


async def test_utc_input_uses_business_local_day(booking_client):
    _, sessions, _ = booking_client
    response = await create(sessions, starts_at="2026-09-19T23:00:00Z")
    assert response.starts_at.isoformat() == "2026-09-19T17:00:00-06:00"


async def test_get_cancel_and_reschedule_preserve_lifecycle(booking_client):
    _, sessions, _ = booking_client
    original = await create(sessions)
    assert await get(sessions, original.id) == original
    moved = await move(sessions, original.id)
    assert moved.id == original.id and moved.customer == original.customer
    assert moved.starts_at.isoformat() == "2026-09-19T15:30:00-06:00"
    first = await cancel(sessions, original.id)
    second = await cancel(sessions, original.id)
    assert first == second and second.status == "cancelled"
    assert original.starts_at.isoformat() in await available_starts(sessions)


@pytest.mark.parametrize("operation", ["get", "cancel", "reschedule"])
async def test_missing_appointment_is_not_found(booking_client, operation):
    _, sessions, _ = booking_client
    action = {"get": get, "cancel": cancel, "reschedule": move}[operation]
    with pytest.raises(NotFoundError):
        await action(sessions, 999)


async def test_invalid_reschedule_preserves_original(booking_client):
    _, sessions, _ = booking_client
    original = await create(sessions)
    with pytest.raises(BookingConflictError):
        await move(sessions, original.id, "2026-09-20T15:30:00-06:00")
    assert await get(sessions, original.id) == original


@pytest.mark.parametrize("start", ["2026-09-19T11:30:00-06:00", "2026-09-19T12:00:00-06:00"])
async def test_reschedule_excludes_its_own_interval(booking_client, start):
    _, sessions, _ = booking_client
    original = await create(sessions)
    response = await move(sessions, original.id, start)
    assert response.starts_at.isoformat() == start


@pytest.mark.parametrize("state,operation", [
    ("CANCELLED", "reschedule"), ("COMPLETED", "cancel"),
    ("COMPLETED", "reschedule"), ("PENDING", "cancel"),
    ("PENDING", "reschedule"),
])
async def test_invalid_lifecycle_transition_preserves_appointment(booking_client, state, operation):
    _, sessions, _ = booking_client
    original = await create(sessions)
    async with sessions.begin() as session:
        (await session.get(Appointment, original.id)).status = state
    action = cancel if operation == "cancel" else move
    with pytest.raises(BookingConflictError):
        await action(sessions, original.id)
    current = await get(sessions, original.id)
    assert current.status == state.lower()
    assert current.starts_at == original.starts_at


async def test_concurrent_create_postgresql(booking_client):
    _, sessions, postgres = booking_client
    if not postgres:
        pytest.skip("Requires TEST_DATABASE_URL pointing to real PostgreSQL")
    results = await asyncio.gather(create(sessions), create(sessions), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, BookingConflictError) for result in results) == 1


async def test_concurrent_reschedule_postgresql(booking_client):
    _, sessions, postgres = booking_client
    if not postgres:
        pytest.skip("Requires real PostgreSQL")
    first = await create(sessions)
    second = await create(sessions, starts_at="2026-09-19T09:00:00-06:00")
    results = await asyncio.gather(move(sessions, first.id), move(sessions, second.id), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, BookingConflictError) for result in results) == 1


async def test_concurrent_create_and_reschedule_postgresql(booking_client):
    _, sessions, postgres = booking_client
    if not postgres:
        pytest.skip("Requires real PostgreSQL")
    original = await create(sessions)
    results = await asyncio.gather(
        move(sessions, original.id),
        create(sessions, starts_at="2026-09-19T15:30:00-06:00"),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, BookingConflictError) for result in results) == 1


async def test_concurrent_cancel_and_reschedule_postgresql(booking_client):
    _, sessions, postgres = booking_client
    if not postgres:
        pytest.skip("Requires real PostgreSQL")
    original = await create(sessions)
    results = await asyncio.gather(
        cancel(sessions, original.id),
        move(sessions, original.id),
        return_exceptions=True,
    )
    assert not isinstance(results[0], Exception)
    assert results[1] is None or isinstance(results[1], (BookingConflictError, type(results[0])))
    assert (await get(sessions, original.id)).status == "cancelled"
