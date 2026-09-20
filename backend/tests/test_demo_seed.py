from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.demo_seed import parse_day, seed_demo
from app.integrations.whatsapp.client import WhatsAppClient, WhatsAppSendError
from app.models import Base, Appointment, Business, Customer, Service
from app.repositories.dashboard import DashboardRepository
from app.services.dashboard import DashboardService
from app.services.reminders import ReminderService


@pytest.fixture
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def seed(sessions, day=date(2026, 9, 18)):
    async with sessions() as session:
        return await seed_demo(session, day)


async def test_repeat_and_second_date(sessions):
    business_id = await seed(sessions)
    assert await seed(sessions) == business_id
    async with sessions() as session:
        data = await DashboardService(DashboardRepository(session)).get_dashboard(business_id, date(2026, 9, 18))
        assert data.summary.model_dump() == dict(total=5, confirmed=4, cancelled=1)
        assert [a.customer.name for a in data.appointments] == ["Mariana", "Sofía", "Daniela", "Andrea", "Fernanda"]
        assert [a.starts_at.strftime("%H:%M") for a in data.appointments] == ["09:00", "10:30", "12:00", "15:00", "17:00"]
        assert all(not a.calendar_synced and not a.reminder_sent for a in data.appointments)
    await seed(sessions, date(2026, 9, 19))
    async with sessions() as session:
        for model, count in ((Business, 1), (Service, 3), (Customer, 5), (Appointment, 10)):
            assert await session.scalar(select(func.count()).select_from(model)) == count


async def test_existing_configuration_and_booking_untouched(sessions):
    business_id = await seed(sessions)
    async with sessions.begin() as session:
        business = await session.get(Business, business_id)
        business.phone_number = "existing-number"
        business.calendar_id = "existing-calendar"
        appointment = await session.scalar(select(Appointment).order_by(Appointment.id))
        appointment.status = "CANCELLED"
    await seed(sessions)
    async with sessions() as session:
        business = await session.get(Business, business_id)
        assert (business.phone_number, business.calendar_id) == ("existing-number", "existing-calendar")
        assert (await session.scalar(select(Appointment).order_by(Appointment.id))).status == "CANCELLED"


async def test_conflict_rolls_back_new_fixtures(sessions):
    business_id = await seed(sessions)
    async with sessions.begin() as session:
        service = await session.scalar(select(Service))
        # Conflict on the second fixture: first fixture must also roll back.
        start = datetime(2026, 9, 19, 16, 30, tzinfo=timezone.utc)
        session.add(Appointment(business_id=business_id, service_id=service.id,
            starts_at=start, ends_at=start + timedelta(hours=1), status="CONFIRMED"))
    with pytest.raises(ValueError, match="Horario ocupado"):
        await seed(sessions, date(2026, 9, 19))
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 6


async def test_fixtures_never_due_and_sender_rejects_before_network(sessions):
    await seed(sessions)
    async with sessions() as session:
        assert await ReminderService(session).find_due(datetime(2026, 9, 18, 14, tzinfo=timezone.utc)) == []
    with pytest.raises(WhatsAppSendError, match="Fictional"):
        await WhatsAppClient(SimpleNamespace()).send_text("demo:bella:mariana", "hola")


def test_date_parser():
    assert parse_day("2026-09-18") == date(2026, 9, 18)
    from app.demo_seed import ZONE
    assert parse_day("today") == datetime.now(ZONE).date()
    for value in ("2026-02-30", "invalid", "9999-12-31"):
        with pytest.raises(ValueError):
            parse_day(value)
