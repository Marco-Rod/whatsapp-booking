"""Manual CREATE E2E: real DB + Google, locally captured WhatsApp replies.

Run from backend with its virtualenv: python ../scripts/replay_google_calendar.py
Enables Bella Studio's primary calendar and leaves one confirmed test booking
and its real event for inspection. Uses a reserved fictional test phone, never
sends WhatsApp messages, and refuses to reuse an existing test conversation.
"""
import asyncio
from datetime import datetime
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

from app.core.config import settings
from app.core.database import Session, engine
from app.integrations.google_calendar.factory import calendar_client_from_token
from app.models import Appointment, Business, Conversation, Customer, InboundMessage
from app.services.calendar import CalendarService
from app.services.whatsapp.webhook import WebhookService

TEST_PHONE = "+15555550199"


class LocalReplies:
    def __init__(self):
        self.messages = []

    async def send_text(self, phone, text):
        self.messages.append(text)


class ObservedCalendar(CalendarService):
    def __init__(self, client):
        super().__init__(client)
        self.calls = 0

    async def sync_created_appointment(self, **kwargs):
        self.calls += 1
        return await super().sync_created_appointment(**kwargs)


async def run():
    calendar_client = calendar_client_from_token(settings.google_calendar_token_file)

    def check_access():
        with calendar_client._service_factory() as service:
            service.calendars().get(calendarId="primary").execute(num_retries=0)

    await asyncio.to_thread(check_access)
    async with Session.begin() as session:
        business = (await session.scalars(select(Business).where(Business.name == "Bella Studio"))).one()
        existing = await session.scalar(select(Conversation.id).where(
            Conversation.business_id == business.id, Conversation.phone == TEST_PHONE))
        customer_exists = await session.scalar(select(Customer.id).where(
            Customer.business_id == business.id, Customer.phone == TEST_PHONE))
        if existing is not None or customer_exists is not None:
            raise RuntimeError("Test phone already used; inspect the previous E2E before another run")
        if not business.phone_number:
            raise RuntimeError("Bella Studio needs a receiving phone configured")
        business.calendar_id = "primary"
        business_id, business_phone = business.id, business.phone_number

    config = settings.model_copy(update={"whatsapp_phone_number_id": "calendar-e2e-local"})
    sender = LocalReplies()
    calendar = ObservedCalendar(calendar_client)
    run_id = uuid4().hex
    counter = 0

    def payload(text):
        nonlocal counter
        counter += 1
        return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
            "metadata": {"phone_number_id": config.whatsapp_phone_number_id,
                         "display_phone_number": business_phone},
            "messages": [{"from": TEST_PHONE, "id": f"calendar-e2e.{run_id}.{counter}",
                          "type": "text", "text": {"body": text}}],
        }}]}]}

    async def process(data):
        async with Session() as session:
            await WebhookService(session, sender, config, calendar_service=calendar).process(data)

    async def conversation():
        async with Session() as session:
            return await session.scalar(select(Conversation).where(
                Conversation.business_id == business_id, Conversation.phone == TEST_PHONE))

    for text in ("hola", "1", "1"):
        await process(payload(text))
    for choice in ("2", "3", "1"):
        await process(payload(choice))
        current = await conversation()
        if current.state == "select_time":
            break
    else:
        raise RuntimeError("No available slots in the conversation's three-day window")
    starts = current.context["starts"]
    noon = next((i for i, start in enumerate(starts, 1)
                 if datetime.fromisoformat(start).strftime("%H:%M") == "12:00"), 1)
    await process(payload(str(noon)))
    if (await conversation()).state != "confirm_appointment":
        raise RuntimeError("Replay did not reach appointment confirmation")
    confirmation = payload("1")
    await process(confirmation)
    reply_count = len(sender.messages)
    await process(confirmation)
    assert len(sender.messages) == reply_count and calendar.calls == 1

    async with Session() as session:
        appointment = (await session.scalars(select(Appointment).join(Customer).where(
            Customer.business_id == business_id, Customer.phone == TEST_PHONE))).one()
        assert appointment.status == "CONFIRMED" and appointment.calendar_event_id
        inbound = await session.scalar(select(InboundMessage).where(
            InboundMessage.external_message_id == confirmation["entry"][0]["changes"][0]["value"]["messages"][0]["id"]))
        assert inbound.processed_at and inbound.payload["sent_count"] == len(inbound.payload["responses"])

    def verify_event():
        with calendar_client._service_factory() as service:
            event = service.events().get(calendarId="primary", eventId=appointment.calendar_event_id).execute(num_retries=0)
        assert event["summary"] == "Corte - Bella Studio"
        assert TEST_PHONE not in event.get("description", "")
        assert datetime.fromisoformat(event["start"]["dateTime"]) == appointment.starts_at
        assert datetime.fromisoformat(event["end"]["dateTime"]) == appointment.ends_at
        return event

    event = await asyncio.to_thread(verify_event)
    print("CREATE E2E OK: PostgreSQL + ConversationEngine + WebhookService + Google Calendar")
    print("Appointment:", appointment.id, appointment.status)
    print("calendar_event_id persisted and verified: yes")
    print("Event:", event["summary"], event["start"]["dateTime"], event["end"]["dateTime"])
    print("Duplicate replay: no additional Calendar call or WhatsApp reply")
    print("WhatsApp replies captured locally:", reply_count)


async def main():
    try:
        await run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
