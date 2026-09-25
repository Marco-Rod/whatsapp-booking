from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from test_booking import booking_client
from test_reminder_processor import reminder_booking, FakeSender, NOW
from app.commands import process_reminders as command
from app.models import Appointment, AppointmentReminder
from app.services.reminder_processor import ReminderProcessor, ReminderProcessingResult
from app.services.reminder_sender import ReminderSendError


@pytest.mark.parametrize("result,code", [(ReminderProcessingResult(), 0),
    (ReminderProcessingResult(sent=2), 0), (ReminderProcessingResult(sent=1, failed=1), 1)])
def test_command_runs_one_cycle_and_reports_counts(monkeypatch, capsys, result, code):
    run = AsyncMock(return_value=result)
    monkeypatch.setattr(command, "run_once", run)
    assert command.main([]) == code
    run.assert_awaited_once_with(None)
    assert capsys.readouterr().out == f"Reminder processing completed: sent={result.sent} failed={result.failed}\n"


def test_fatal_error_exit_is_sanitized(monkeypatch, capsys):
    monkeypatch.setattr(command, "run_once", AsyncMock(side_effect=RuntimeError("secret-value")))
    assert command.main([]) == 2
    output = capsys.readouterr()
    assert "RuntimeError" in output.err and "secret-value" not in output.err


async def test_runner_disposes_engine_on_failure(monkeypatch):
    engine = AsyncMock()
    processor = AsyncMock()
    processor.process_once.side_effect = RuntimeError("failure")
    monkeypatch.setattr(command, "create_async_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(command, "ReminderProcessor", lambda *args: processor)
    with pytest.raises(RuntimeError):
        await command.run_once()
    engine.dispose.assert_awaited_once()


async def test_empty_queue_succeeds(booking_client):
    _, sessions, _ = booking_client
    sender = FakeSender()
    assert await ReminderProcessor(sessions, sender).process_once(NOW) == ReminderProcessingResult()
    assert sender.messages == []


async def test_delayed_cycle_continues_after_individual_failure(reminder_booking):
    sessions, first_id, _ = reminder_booking
    async with sessions.begin() as session:
        first = await session.get(Appointment, first_id)
        second = Appointment(business_id=first.business_id, service_id=first.service_id,
                             customer_id=first.customer_id, status="CONFIRMED",
                             starts_at=first.starts_at, ends_at=first.ends_at)
        session.add(second)

    class Sender(FakeSender):
        attempts = 0

        async def send(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise ReminderSendError("offline")
            await super().send(**kwargs)

    sender = Sender()
    late = NOW + timedelta(minutes=5)
    result = await ReminderProcessor(sessions, sender).process_once(late)
    assert result == ReminderProcessingResult(sent=1, failed=1)
    assert sender.attempts == 2 and len(sender.messages) == 1
    async with sessions() as session:
        records = list(await session.scalars(select(AppointmentReminder).order_by(AppointmentReminder.appointment_id)))
        assert records[0].scheduled_for == records[1].scheduled_for == NOW
        assert records[0].sent_at is None and records[1].sent_at == late
        assert all(r.claim_token is None for r in records)
