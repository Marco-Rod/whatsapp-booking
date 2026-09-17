import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from test_booking import booking_client
from app.core.config import Settings
from app.integrations.whatsapp.client import WhatsAppClient
from app.integrations.whatsapp.reminder_sender import WhatsAppReminderSender
from app.models import Appointment, AppointmentReminder, Customer
from app.services.reminder_processor import ReminderProcessor, format_reminder
from app.services.reminder_sender import ReminderSendError
from app.services.reminders import ReminderService

NOW = datetime(2026, 9, 17, 22, tzinfo=timezone.utc)


class FakeSender:
    def __init__(self):
        self.messages = []
        self.error = None

    async def send(self, **kwargs):
        if self.error:
            raise self.error
        self.messages.append(kwargs)


@pytest_asyncio.fixture
async def reminder_booking(booking_client):
    _, sessions, postgres = booking_client
    async with sessions.begin() as session:
        customer = Customer(business_id=1, name="Test", phone="+15555550199")
        session.add(customer)
        await session.flush()
        appointment = Appointment(business_id=1, service_id=1, customer_id=customer.id,
                                  status="CONFIRMED", starts_at=NOW + timedelta(hours=24),
                                  ends_at=NOW + timedelta(hours=25))
        session.add(appointment)
        await session.flush()
        appointment_id = appointment.id
    return sessions, appointment_id, postgres


async def reminder(sessions):
    async with sessions() as session:
        return (await session.scalars(select(AppointmentReminder))).one()


async def test_ack_sets_sent_at_and_two_more_runs_send_nothing(reminder_booking):
    sessions, appointment_id, _ = reminder_booking
    observed = []

    class TrackedSession(AsyncSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            observed.append(self)

    tracked = async_sessionmaker(sessions.kw["bind"], class_=TrackedSession, expire_on_commit=False)

    class Sender(FakeSender):
        async def send(self, **kwargs):
            assert not any(session.in_transaction() for session in observed)
            pending = await reminder(sessions)
            assert pending.claim_token and pending.sent_at is None
            await super().send(**kwargs)

    sender = Sender()
    processor = ReminderProcessor(tracked, sender)
    assert await processor.process_due_reminders(NOW, appointment_id=appointment_id) == 1
    assert await processor.process_due_reminders(NOW) == 0
    assert await processor.process_due_reminders(NOW + timedelta(minutes=1)) == 0
    record = await reminder(sessions)
    assert record.sent_at == NOW and record.claim_token is None
    assert sender.messages == [{"phone": "+15555550199", "message":
        "⏰ Recordatorio de tu cita\n\nCut\n18 de septiembre a las 4:00 PM.\n\n"
        "Si necesitas hacer un cambio, responde a este mensaje."}]


async def test_send_failure_leaves_pending_and_retry_can_succeed(reminder_booking):
    sessions, _, _ = reminder_booking
    sender = FakeSender()
    sender.error = ReminderSendError("unavailable")
    processor = ReminderProcessor(sessions, sender)
    assert await processor.process_due_reminders(NOW) == 0
    record = await reminder(sessions)
    assert record.sent_at is None and record.claim_token is None
    sender.error = None
    assert await processor.process_due_reminders(NOW + timedelta(minutes=1)) == 1
    assert (await reminder(sessions)).sent_at == NOW + timedelta(minutes=1)


@pytest.mark.parametrize("change", ["cancel", "reschedule", "missing_customer"])
async def test_rechecks_booking_after_discovery(reminder_booking, monkeypatch, change):
    sessions, appointment_id, _ = reminder_booking
    sender = FakeSender()
    processor = ReminderProcessor(sessions, sender)
    original = processor._claim

    async def changed_before_claim(*args):
        async with sessions.begin() as session:
            appointment = await session.get(Appointment, appointment_id)
            if change == "cancel":
                appointment.status = "CANCELLED"
            elif change == "reschedule":
                appointment.starts_at += timedelta(hours=1)
                appointment.ends_at += timedelta(hours=1)
            else:
                appointment.customer_id = None
        return await original(*args)

    monkeypatch.setattr(processor, "_claim", changed_before_claim)
    assert await processor.process_due_reminders(NOW) == 0
    assert sender.messages == []
    record = await reminder(sessions)
    assert record.sent_at is None and record.claim_token is None


async def test_cancelled_never_sends(reminder_booking):
    sessions, appointment_id, _ = reminder_booking
    async with sessions.begin() as session:
        (await session.get(Appointment, appointment_id)).status = "CANCELLED"
    sender = FakeSender()
    assert await ReminderProcessor(sessions, sender).process_due_reminders(NOW) == 0
    assert sender.messages == []


async def test_concurrent_processors_only_one_send(reminder_booking):
    sessions, _, postgres = reminder_booking
    if not postgres:
        pytest.skip("Real PostgreSQL is required for independent concurrent workers")
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingSender(FakeSender):
        async def send(self, **kwargs):
            await super().send(**kwargs)
            entered.set()
            await release.wait()

    # Both workers deliberately discover the same stale pending row; only the
    # atomic UPDATE may choose the sender, not discovery-time filtering.
    async with sessions() as session:
        due = await ReminderService(session).find_due(NOW)
    first, second = ReminderProcessor(sessions, BlockingSender()), ReminderProcessor(sessions, FakeSender())
    first_claim = await first._claim(due[0].id, "worker-a", NOW)
    assert first_claim is not None
    assert await second._claim(due[0].id, "worker-b", NOW) is None
    await first._finish(due[0].id, "worker-a", sent_at=None)
    running = asyncio.create_task(first.process_due_reminders(NOW))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        assert await second.process_due_reminders(NOW) == 0
    finally:
        release.set()
    assert await running == 1
    assert len(first.sender.messages) == 1 and second.sender.messages == []


async def test_unknown_interruption_keeps_claim_without_resending(reminder_booking):
    sessions, _, _ = reminder_booking
    sender = FakeSender()
    sender.error = RuntimeError("interrupted")
    processor = ReminderProcessor(sessions, sender)
    with pytest.raises(RuntimeError, match="interrupted"):
        await processor.process_due_reminders(NOW)
    record = await reminder(sessions)
    assert record.sent_at is None and record.claim_token
    sender.error = None
    assert await processor.process_due_reminders(NOW) == 0
    assert sender.messages == []


async def test_db_failure_after_ack_does_not_automatically_resend(reminder_booking, monkeypatch):
    sessions, _, _ = reminder_booking
    sender = FakeSender()
    processor = ReminderProcessor(sessions, sender)

    async def fail(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(processor, "_finish", fail)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await processor.process_due_reminders(NOW)
    assert len(sender.messages) == 1
    record = await reminder(sessions)
    assert record.sent_at is None and record.claim_token
    assert await ReminderProcessor(sessions, sender).process_due_reminders(NOW) == 0


@pytest.mark.parametrize("utc,zone,expected", [
    ("2026-09-18T02:00:00+00:00", "America/Mexico_City", "17 de septiembre a las 8:00 PM"),
    ("2026-09-18T06:00:00+00:00", "America/Mexico_City", "18 de septiembre a las 12:00 AM"),
    ("2026-09-18T18:00:00+00:00", "America/Mexico_City", "18 de septiembre a las 12:00 PM"),
])
def test_formatter_uses_local_day_and_twelve_hour_clock(utc, zone, expected):
    assert expected in format_reminder(service_name="Corte", starts_at=datetime.fromisoformat(utc),
                                      business_timezone=zone)


@pytest.mark.parametrize("ack", [True, False])
async def test_whatsapp_adapter_acknowledgement_controls_sent_at(reminder_booking, ack):
    sessions, _, _ = reminder_booking
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.reminder"}]} if ack else {})

    config = Settings(_env_file=None, whatsapp_access_token="test", whatsapp_phone_number_id="123",
                      whatsapp_api_version="v99.0")
    sender = WhatsAppReminderSender(WhatsAppClient(config, httpx.MockTransport(response)))
    assert await ReminderProcessor(sessions, sender).process_due_reminders(NOW) == int(ack)
    assert len(requests) == 1
    assert (await reminder(sessions)).sent_at == (NOW if ack else None)


async def test_appointment_filter_does_not_send_other_bookings(reminder_booking):
    sessions, appointment_id, _ = reminder_booking
    sender = FakeSender()
    assert await ReminderProcessor(sessions, sender).process_due_reminders(
        NOW, appointment_id=appointment_id + 1000) == 0
    assert sender.messages == []


@pytest.mark.parametrize("phone,destination", [
    ("+525512345678", "+525512345678"),
    ("+5215512345678", "+5215512345678"),
    ("+15555550199", "+15555550199"),
])
async def test_adapter_preserves_configured_recipient(phone, destination):
    client = AsyncMock(spec=WhatsAppClient)
    await WhatsAppReminderSender(client).send(phone=phone, message="Reminder")
    client.send_text.assert_awaited_once_with(destination, "Reminder")
