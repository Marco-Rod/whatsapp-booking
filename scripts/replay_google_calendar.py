"""Manual CREATE E2E: real DB + Google, locally captured WhatsApp replies.

Run from backend with its virtualenv:
python ../scripts/replay_google_calendar.py --business-id 1
Uses the business's OAuth Calendar connection and leaves one confirmed test booking
and its real event for inspection. Uses a reserved fictional test phone, never
sends WhatsApp messages, and refuses to reuse an existing test conversation.
"""
import argparse
import asyncio
from datetime import datetime
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select

from app.core.config import settings
from app.core.database import Session, engine
from app.models import Appointment, Business, Conversation, Customer, InboundMessage
from app.services.calendar_resolver import CalendarClientResolver, ResolvedCalendar
from app.services.whatsapp.webhook import WebhookService

TEST_PHONE = "+15555550199"


class LocalReplies:
    def __init__(self):
        self.messages = []

    async def send_text(self, phone, text):
        self.messages.append(text)


class ObservedClient:
    def __init__(self, client, counter):
        self.client = client
        self.counter = counter

    async def create_event(self, *args, **kwargs):
        self.counter["create"] += 1
        return await self.client.create_event(*args, **kwargs)


class ObservedResolver:
    def __init__(self, resolver, counter):
        self.resolver = resolver
        self.counter = counter

    async def resolve(self, business_id):
        resolved = await self.resolver.resolve(business_id)
        if resolved is None:
            return None
        return ResolvedCalendar(
            calendar_id=resolved.calendar_id,
            client=ObservedClient(resolved.client, self.counter),
        )


async def run(business_id: int):
    async with Session.begin() as session:
        business = await session.get(Business, business_id)
        if business is None:
            raise RuntimeError(f"Business {business_id} does not exist")
        resolved = await CalendarClientResolver(session).resolve(business_id)
        if resolved is None:
            raise RuntimeError(f"Business {business_id} has no Google Calendar connection")
        existing = await session.scalar(select(Conversation.id).where(
            Conversation.business_id == business.id, Conversation.phone == TEST_PHONE))
        customer_exists = await session.scalar(select(Customer.id).where(
            Customer.business_id == business.id, Customer.phone == TEST_PHONE))
        if existing is not None or customer_exists is not None:
            raise RuntimeError("Test phone already used; inspect the previous E2E before another run")
        if not business.phone_number:
            raise RuntimeError("Business needs a receiving phone configured")
        business_id, business_phone = business.id, business.phone_number

    config = settings.model_copy(update={"whatsapp_phone_number_id": "calendar-e2e-local"})
    sender = LocalReplies()
    counter = {"create": 0}
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
            resolver = ObservedResolver(
                CalendarClientResolver(session),
                counter,
            )
            await WebhookService(
                session,
                sender,
                config,
                calendar_resolver=resolver,
            ).process(data)

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
    assert len(sender.messages) == reply_count and counter["create"] == 1

    async with Session() as session:
        appointment = (await session.scalars(select(Appointment).join(Customer).where(
            Customer.business_id == business_id, Customer.phone == TEST_PHONE))).one()
        assert appointment.status == "CONFIRMED" and appointment.calendar_event_id
        inbound = await session.scalar(select(InboundMessage).where(
            InboundMessage.external_message_id == confirmation["entry"][0]["changes"][0]["value"]["messages"][0]["id"]))
        assert inbound.processed_at and inbound.payload["sent_count"] == len(inbound.payload["responses"])

    def verify_event():
        with resolved.client._service_factory() as service:
            event = service.events().get(
                calendarId=resolved.calendar_id,
                eventId=appointment.calendar_event_id,
            ).execute(num_retries=0)
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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--business-id", type=int, required=True)
    return parser.parse_args()


async def main(business_id: int):
    try:
        await run(business_id)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.business_id))
