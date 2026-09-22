import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from test_booking import booking_client  # Shared isolated database fixture.
from app.models import Appointment, Conversation, Customer, InboundMessage, Service
from app.schemas.booking import AppointmentCreate, CustomerInput
from app.services.booking.booking import BookingService
from app.services.booking.availability import NotFoundError
from app.services.conversation.engine import ConversationEngine

PHONE = "+523312345678"
NOW = datetime(2026, 9, 18, 18, tzinfo=timezone.utc)


async def handle(sessions, text, phone=PHONE, business_id=1, now=NOW):
    # Recreate the engine/session on every message to prove persistence.
    async with sessions() as session:
        return await ConversationEngine(session, clock=lambda: now).handle_message(business_id, phone, text)


async def conversation(sessions, phone=PHONE, business_id=1):
    async with sessions() as session:
        return await session.scalar(select(Conversation).where(
            Conversation.phone == phone, Conversation.business_id == business_id))


async def to_confirmation(sessions, phone=PHONE):
    for text in ("hola", "1", "1", "2", "2"):
        result = await handle(sessions, text, phone)
    assert "¿Confirmar?" in result.messages[0]


async def test_full_conversation_creates_real_appointment(booking_client):
    _, sessions, _ = booking_client
    await to_confirmation(sessions)
    selected = (await conversation(sessions)).context["starts_at"]
    result = await handle(sessions, "1")

    assert len(result.messages) == 1
    assert "Tu cita está confirmada" in result.messages[0]

    current = await conversation(sessions)
    assert current.state == "main_menu"
    assert current.context == {}
    async with sessions() as session:
        appointment = await session.scalar(select(Appointment))
        assert result.appointment_id == appointment.id
        customer = await session.get(Customer, appointment.customer_id)
        assert customer.phone == PHONE
        assert appointment.service_id == 1
        assert appointment.status == "CONFIRMED"
        assert appointment.starts_at == datetime.fromisoformat(selected).astimezone(timezone.utc)
        assert await session.scalar(select(func.count()).select_from(InboundMessage)) == 0


@pytest.mark.parametrize("steps,state", [(("hola",),"main_menu"),
    (("hola","1"),"select_service"), (("hola","1","1"),"select_date"),
    (("hola","1","1","2"),"select_time"), (("hola","1","1","2","2"),"confirm_appointment")])
async def test_invalid_input_and_universal_cancel(booking_client, steps, state):
    _, sessions, _ = booking_client
    for text in steps:
        await handle(sessions, text)
    before = await conversation(sessions)
    result = await handle(sessions, "999999999999999999999999999999999999")
    after = await conversation(sessions)
    assert result.appointment_id is None
    assert after.state == state
    assert after.context == before.context
    if state != "main_menu":
        assert result.messages[0] == "No reconocí esa opción."
    await handle(sessions, " cancelar ")
    after = await conversation(sessions)
    assert after.state == "main_menu"
    assert after.context == {}


async def test_decline_confirmation(booking_client):
    _, sessions, _ = booking_client
    await to_confirmation(sessions)
    await handle(sessions, "2")
    assert (await conversation(sessions)).context == {}
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 0


async def test_dates_use_business_timezone(booking_client):
    _, sessions, _ = booking_client
    now = datetime(2026, 9, 19, 2, tzinfo=timezone.utc)  # Still Sep 18 in Mexico.
    for text in ("hola","1","1"):
        await handle(sessions, text, now=now)
    assert (await conversation(sessions)).context["dates"] == ["2026-09-18","2026-09-19","2026-09-20"]


async def test_closed_day_and_empty_services(booking_client):
    _, sessions, _ = booking_client
    for text in ("hola","1","1","3"):
        result = await handle(sessions, text)
    assert "No hay horarios" in result.messages[0]
    assert (await conversation(sessions)).state == "select_date"
    async with sessions.begin() as session:
        for service in await session.scalars(select(Service).where(Service.business_id == 1)):
            service.is_active = False
    await handle(sessions, "CANCELAR")
    result = await handle(sessions, "1")
    assert "No hay servicios" in result.messages[0]
    assert (await conversation(sessions)).state == "main_menu"


async def test_stale_slot_conflict_recovers_without_wrong_booking(booking_client):
    _, sessions, _ = booking_client
    await to_confirmation(sessions)
    selected = (await conversation(sessions)).context["starts_at"]
    async with sessions() as session:
        await BookingService(session).create_appointment(AppointmentCreate(
            business_id=1, service_id=1, starts_at=selected,
            customer=CustomerInput(name="Other", phone="+523300000099")))
    result = await handle(sessions, "1")
    assert "ya no está disponible" in result.messages[0]
    current = await conversation(sessions)
    assert current.state == "select_time"
    assert selected not in current.context["starts"]
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 1


async def test_confirmation_failure_rolls_back_booking_and_context(booking_client, monkeypatch):
    _, sessions, _ = booking_client
    await to_confirmation(sessions)
    before = (await conversation(sessions)).context
    original = BookingService.create_appointment_in_transaction

    async def fail_after_insert(self, request):
        await original(self, request)
        raise RuntimeError("Simulated failure after appointment INSERT")

    with monkeypatch.context() as patch:
        patch.setattr(BookingService, "create_appointment_in_transaction", fail_after_insert)
        with pytest.raises(RuntimeError, match="Simulated failure"):
            await handle(sessions, "1")
    current = await conversation(sessions)
    assert current.state == "confirm_appointment"
    assert current.context == before
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 0
        assert await session.scalar(select(func.count()).select_from(Customer)) == 0
    assert "confirmada" in (await handle(sessions, "1")).messages[0]


async def test_phone_and_business_isolation(booking_client):
    _, sessions, _ = booking_client
    await handle(sessions, "1")
    await handle(sessions, "hola", phone="+523300000098")
    await handle(sessions, "hola", business_id=2)
    assert (await conversation(sessions)).state == "select_service"
    assert (await conversation(sessions, phone="+523300000098")).state == "main_menu"
    assert (await conversation(sessions, business_id=2)).state == "main_menu"
    with pytest.raises(NotFoundError):
        await handle(sessions, "hola", business_id=999)


async def test_concurrent_confirmation_postgresql(booking_client):
    _, sessions, postgres = booking_client
    if not postgres:
        pytest.skip("Requires real PostgreSQL")
    await to_confirmation(sessions)
    results = await asyncio.wait_for(asyncio.gather(handle(sessions, "1"), handle(sessions, "1")), 20)
    assert sum("confirmada" in r.messages[0] for r in results) == 1
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 1
        assert await session.scalar(select(func.count()).select_from(Conversation)) == 1
