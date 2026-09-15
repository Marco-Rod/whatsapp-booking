import asyncio
import os
from datetime import time
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_session
from app.main import app
from app.models import Appointment, Base, Business, BusinessHours, Customer, Service


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
            session.add_all([Business(id=1, name="One", timezone="America/Mexico_City"),
                             Business(id=2, name="Two", timezone="America/Mexico_City")])
            await session.flush()
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
    return {"business_id": 1, "service_id": 1,
            "customer": {"name": "Andrea", "phone": "+523312345678"},
            "starts_at": "2026-09-19T11:30:00-06:00", **overrides}


async def create(client, **overrides):
    return await client.post("/api/v1/appointments", json=payload(**overrides))


async def test_create_persists_and_blocks_availability(booking_client):
    client, sessions, _ = booking_client
    response = await create(client)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["ends_at"] == "2026-09-19T12:30:00-06:00"
    async with sessions() as session:
        appointment = await session.get(Appointment, body["id"])
        assert appointment.customer_id == body["customer"]["id"]
        assert appointment.status == "CONFIRMED"
        assert appointment.starts_at.isoformat() == "2026-09-19T17:30:00+00:00"
    response = await client.get("/api/v1/availability", params={
        "business_id": 1, "service_id": 1, "date": "2026-09-19"})
    assert body["starts_at"] not in [slot["starts_at"] for slot in response.json()["slots"]]


async def test_customer_reuse_and_business_isolation(booking_client):
    client, sessions, _ = booking_client
    first = await create(client)
    second = await create(client, starts_at="2026-09-19T13:00:00-06:00")
    other = await create(client, business_id=2, service_id=2)
    assert [r.status_code for r in (first, second, other)] == [201, 201, 201]
    assert first.json()["customer"]["id"] == second.json()["customer"]["id"]
    assert first.json()["customer"]["id"] != other.json()["customer"]["id"]
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Customer)) == 2


@pytest.mark.parametrize("overrides,status", [
    ({"business_id": 999}, 404), ({"service_id": 999}, 404), ({"service_id": 2}, 404),
    ({"service_id": 3}, 409), ({"starts_at": "2026-09-19T08:30:00-06:00"}, 409),
    ({"starts_at": "2026-09-19T18:00:00-06:00"}, 409),
    ({"starts_at": "2026-09-20T11:30:00-06:00"}, 409),
    ({"starts_at": "2026-09-21T11:30:00-06:00"}, 409),
    ({"starts_at": "2026-09-19T11:15:00-06:00"}, 409),
    ({"service_id": 4, "starts_at": "2026-09-19T16:30:00-06:00"}, 409),
    ({"starts_at": "2026-09-19T11:30:00"}, 422), ({"status": "cancelled"}, 422),
    ({"ends_at": "2026-09-19T12:00:00-06:00"}, 422),
    ({"customer": {"name": " ", "phone": "+523312345678"}}, 422),
    ({"customer": {"name": "Andrea", "phone": "3312345678"}}, 422),
])
async def test_rejections_leave_no_records(booking_client, overrides, status):
    client, sessions, _ = booking_client
    response = await create(client, **overrides)
    assert response.status_code == status, response.text
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Customer)) == 0
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 0


@pytest.mark.parametrize("hour,status", [("11:30",409),("11:00",409),("12:00",409),("10:30",201),("12:30",201)])
async def test_overlap_and_adjacency(booking_client, hour, status):
    client, _, _ = booking_client
    assert (await create(client)).status_code == 201
    assert (await create(client, starts_at=f"2026-09-19T{hour}:00-06:00")).status_code == status


async def test_utc_input_uses_business_local_day(booking_client):
    response = await create(booking_client[0], starts_at="2026-09-19T23:00:00Z")
    assert response.status_code == 201
    assert response.json()["starts_at"] == "2026-09-19T17:00:00-06:00"


async def test_concurrent_requests_postgresql(booking_client):
    client, sessions, postgres = booking_client
    if not postgres:
        pytest.skip("Requires TEST_DATABASE_URL pointing to real PostgreSQL")
    responses = await asyncio.gather(create(client), create(client))
    assert sorted(r.status_code for r in responses) == [201, 409]
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 1
        assert await session.scalar(select(func.count()).select_from(Customer)) == 1


async def available_starts(client):
    response = await client.get("/api/v1/availability", params={
        "business_id": 1, "service_id": 1, "date": "2026-09-19"})
    assert response.status_code == 200
    return [slot["starts_at"] for slot in response.json()["slots"]]


async def move(client, appointment_id, start="2026-09-19T15:30:00-06:00"):
    return await client.post(f"/api/v1/appointments/{appointment_id}/reschedule", json={"starts_at": start})


async def test_get_and_idempotent_cancel_frees_slot(booking_client):
    client, sessions, _ = booking_client
    original = (await create(client)).json()
    path = f'/api/v1/appointments/{original["id"]}'
    assert (await client.get(path)).json() == original
    assert original["starts_at"] not in await available_starts(client)
    first = await client.post(path + "/cancel")
    second = await client.post(path + "/cancel")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert second.json()["status"] == "cancelled"
    assert original["starts_at"] in await available_starts(client)
    async with sessions() as session:
        assert (await session.get(Appointment, original["id"])).status == "CANCELLED"
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 1


async def test_reschedule_moves_interval_and_reuses_identity(booking_client):
    client, _, _ = booking_client
    original = (await create(client)).json()
    response = await move(client, original["id"])
    assert response.status_code == 200
    moved = response.json()
    assert moved["id"] == original["id"]
    assert moved["customer"] == original["customer"]
    assert moved["status"] == "confirmed"
    assert moved["ends_at"] == "2026-09-19T16:30:00-06:00"
    slots = await available_starts(client)
    assert original["starts_at"] in slots
    assert moved["starts_at"] not in slots
    assert (await client.get(f'/api/v1/appointments/{original["id"]}')).json() == moved


@pytest.mark.parametrize("start", ["2026-09-19T11:30:00-06:00", "2026-09-19T12:00:00-06:00"])
async def test_reschedule_excludes_self(booking_client, start):
    client, _, _ = booking_client
    original = (await create(client)).json()
    response = await move(client, original["id"], start)
    assert response.status_code == 200
    assert response.json()["starts_at"] == start


async def test_failed_reschedule_preserves_both_appointments(booking_client):
    client, _, _ = booking_client
    first = (await create(client)).json()
    second = (await create(client, starts_at="2026-09-19T15:30:00-06:00")).json()
    response = await move(client, first["id"])
    assert response.status_code == 409
    for original in (first, second):
        assert (await client.get(f'/api/v1/appointments/{original["id"]}')).json() == original


@pytest.mark.parametrize("state,operation", [("CANCELLED","reschedule"),("COMPLETED","cancel"),
    ("COMPLETED","reschedule"),("PENDING","cancel"),("PENDING","reschedule")])
async def test_invalid_lifecycle_transition(booking_client, state, operation):
    client, sessions, _ = booking_client
    original = (await create(client)).json()
    async with sessions.begin() as session:
        appointment = await session.get(Appointment, original["id"])
        appointment.status = state
    if operation == "cancel":
        response = await client.post(f'/api/v1/appointments/{original["id"]}/cancel')
    else:
        response = await move(client, original["id"])
    assert response.status_code == 409
    current = (await client.get(f'/api/v1/appointments/{original["id"]}')).json()
    assert current["status"] == state.lower()
    assert current["starts_at"] == original["starts_at"]


@pytest.mark.parametrize("operation", ["get", "cancel", "reschedule"])
async def test_missing_appointment(booking_client, operation):
    client, _, _ = booking_client
    if operation == "get":
        response = await client.get("/api/v1/appointments/999")
    elif operation == "cancel":
        response = await client.post("/api/v1/appointments/999/cancel")
    else:
        response = await move(client, 999)
    assert response.status_code == 404


@pytest.mark.parametrize("start,status", [("2026-09-20T15:30:00-06:00",409),
    ("2026-09-19T17:30:00-06:00",409),("2026-09-19T15:15:00-06:00",409),
    ("2026-09-19T15:30:00",422)])
async def test_invalid_reschedule_keeps_original(booking_client, start, status):
    client, _, _ = booking_client
    original = (await create(client)).json()
    assert (await move(client, original["id"], start)).status_code == status
    assert (await client.get(f'/api/v1/appointments/{original["id"]}')).json() == original


async def test_concurrent_reschedules_postgresql(booking_client):
    client, sessions, postgres = booking_client
    if not postgres:
        pytest.skip("Requires real PostgreSQL")
    first = (await create(client)).json()
    second = (await create(client, starts_at="2026-09-19T09:00:00-06:00")).json()
    responses = await asyncio.wait_for(asyncio.gather(
        move(client, first["id"]), move(client, second["id"])), timeout=20)
    assert sorted(r.status_code for r in responses) == [200, 409]
    async with sessions() as session:
        appointments = list(await session.scalars(select(Appointment)))
        assert len(appointments) == 2
        assert sum(a.starts_at.hour == 21 and a.starts_at.minute == 30 for a in appointments) == 1
    for original, response in zip((first, second), responses):
        if response.status_code == 409:
            assert (await client.get(f'/api/v1/appointments/{original["id"]}')).json() == original


async def test_concurrent_create_and_reschedule_postgresql(booking_client):
    client, _, postgres = booking_client
    if not postgres:
        pytest.skip("Requires real PostgreSQL")
    original = (await create(client)).json()
    moved, created = await asyncio.wait_for(asyncio.gather(
        move(client, original["id"]), create(client, starts_at="2026-09-19T15:30:00-06:00")), timeout=20)
    assert (moved.status_code, created.status_code) in [(200,409),(409,201)]


async def test_concurrent_cancel_and_reschedule_postgresql(booking_client):
    client, _, postgres = booking_client
    if not postgres:
        pytest.skip("Requires real PostgreSQL")
    original = (await create(client)).json()
    path = f'/api/v1/appointments/{original["id"]}'
    cancelled, moved = await asyncio.wait_for(asyncio.gather(client.post(path + "/cancel"),
        move(client, original["id"])), timeout=20)
    assert cancelled.status_code == 200
    assert moved.status_code in (200,409)
    assert (await client.get(path)).json()["status"] == "cancelled"
