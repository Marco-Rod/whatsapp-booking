from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.main import app
from app.core.database import get_session
from app.models import Base, Business, BusinessHours, Service, Appointment
from app.services.booking.availability import generate_slots

ZONE = ZoneInfo("America/Mexico_City")


def dt(hour, minute=0):
    return datetime(2026, 9, 19, hour, minute, tzinfo=ZONE)


@pytest.mark.parametrize("duration,count,last", [(30,18,"17:30"),(45,17,"17:00"),(60,17,"17:00"),(120,15,"16:00"),(600,0,None)])
def test_durations(duration, count, last):
    slots = generate_slots(dt(9), dt(18), duration, 30, [])
    assert len(slots) == count
    if last:
        assert slots[-1].starts_at.strftime("%H:%M") == last


@pytest.mark.parametrize("start,end,allowed", [(dt(10),dt(11),False),(dt(9,30),dt(10,30),False),
    (dt(10,30),dt(11,30),False),(dt(9),dt(12),False),(dt(10,15),dt(10,45),False),
    (dt(9),dt(10),True),(dt(11),dt(12),True)])
def test_overlap(start, end, allowed):
    slots = generate_slots(dt(10), dt(11), 60, 30, [(start,end)])
    assert bool(slots) is allowed


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        session.add_all([Business(id=1,name="Demo",timezone=str(ZONE)), Business(id=2,name="Other",timezone=str(ZONE))])
        await session.flush()
        session.add_all([Service(id=1,business_id=1,name="Corte",duration_minutes=60),
            Service(id=2,business_id=2,name="Other",duration_minutes=60),
            Service(id=3,business_id=1,name="Inactive",duration_minutes=60,is_active=False),
            BusinessHours(business_id=1,weekday=5,start_time=time(9),end_time=time(18)),
            BusinessHours(business_id=1,weekday=6,is_closed=True)])
        await session.commit()
        async def override():
            yield session
        app.dependency_overrides[get_session] = override
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
                yield http, session
        finally:
            app.dependency_overrides.clear()
    await engine.dispose()


async def query(http, **kwargs):
    return await http.get("/api/v1/availability", params={"business_id":1,"service_id":1,"date":"2026-09-19",**kwargs})


async def test_api_normal(client):
    http,_ = client
    response = await query(http)
    assert response.status_code == 200
    assert len(response.json()["slots"]) == 17
    assert response.json()["slots"][0]["starts_at"] == "2026-09-19T09:00:00-06:00"


@pytest.mark.parametrize("params,status", [({"business_id":99},404),({"service_id":99},404),
    ({"service_id":2},404),({"service_id":3},404),({"date":"invalid"},422),({"business_id":0},422)])
async def test_invalid(client, params, status):
    assert (await query(client[0], **params)).status_code == status


@pytest.mark.parametrize("day", ["2026-09-20", "2026-09-21"])
async def test_closed_or_missing_hours(client, day):
    response = await query(client[0], date=day)
    assert response.status_code == 200
    assert response.json()["slots"] == []


@pytest.mark.parametrize("status,count", [("CANCELLED",17),("COMPLETED",17),("PENDING",14),("CONFIRMED",14)])
async def test_appointment_status(client, status, count):
    http,session = client
    session.add(Appointment(business_id=1,service_id=1, starts_at=dt(10).astimezone(timezone.utc),
        ends_at=dt(11).astimezone(timezone.utc),status=status))
    await session.commit()
    response = await query(http)
    assert len(response.json()["slots"]) == count
