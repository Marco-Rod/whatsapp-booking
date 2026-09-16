from datetime import datetime, timezone
from hmac import compare_digest
import logging

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from app.integrations.google_calendar.errors import GoogleCalendarError
from app.models import Appointment, Business, Customer, Service
from app.integrations.whatsapp.client import WhatsAppConfigurationError
from app.integrations.whatsapp.parser import parse_messages
from app.repositories.booking import BookingRepository
from app.repositories.inbound_messages import InboundMessageRepository
from app.services.conversation.engine import ConversationEngine

logger = logging.getLogger(__name__)


def verify_webhook(config, mode, token, challenge):
    expected = config.whatsapp_verify_token.get_secret_value()
    if not expected:
        raise WhatsAppConfigurationError("Webhook verification is not configured")
    if mode != "subscribe" or not token or not compare_digest(token.encode(), expected.encode()):
        raise PermissionError("Invalid verification token")
    return challenge


class WebhookService:
    def __init__(self, session, client, config, engine=None, calendar_service=None):
        self.session = session
        self.client = client
        self.config = config
        self.repository = InboundMessageRepository(session)
        self.engine = engine or ConversationEngine(session)
        self.calendar_service = calendar_service

    async def process(self, payload):
        messages = parse_messages(payload)
        for message in messages:
            if not self.config.whatsapp_phone_number_id:
                raise WhatsAppConfigurationError("WhatsApp receiving number is not configured")
            if message.phone_number_id != self.config.whatsapp_phone_number_id:
                continue
            appointment_id = None
            async with self.session.begin():
                ids = await self.repository.business_ids(message.business_phone)
                if len(ids) != 1:
                    raise WhatsAppConfigurationError("Receiving number must map to exactly one business")
                business_id = ids[0]
                await BookingRepository(self.session).lock_business(business_id)
                inbound = await self.repository.find(business_id, message.external_message_id)
                if inbound is None:
                    inbound = await self.repository.add(business_id, message)
                if inbound.processed_at is None:
                    result = await self.engine.handle_message_in_transaction(
                        business_id, inbound.phone, message.text)
                    appointment_id = result.appointment_id
                    # Store replies in the same commit as conversation/booking. Split long menus.
                    responses = [text[i:i + 4096] for text in result.messages for i in range(0, len(text), 4096)]
                    inbound.payload = {**inbound.payload, "responses": responses, "sent_count": 0}
                    inbound.processed_at = datetime.now(timezone.utc)
                inbound_id = inbound.id
            if appointment_id is not None:
                await self._sync_calendar(appointment_id)
            await self._deliver(inbound_id)

    async def _sync_calendar(self, appointment_id: int) -> None:
        if self.calendar_service is None:
            return
        try:
            # Finish the read transaction too before making the external call.
            async with self.session.begin():
                appointment = await self.session.get(Appointment, appointment_id)
                if appointment is None or appointment.calendar_event_id is not None:
                    return
                business = await self.session.get(Business, appointment.business_id)
                if business is None or not business.calendar_id:
                    return
                service = await self.session.get(Service, appointment.service_id)
                customer = await self.session.get(Customer, appointment.customer_id) if appointment.customer_id else None
                if service is None or customer is None:
                    return
                # Loaded scalar snapshots remain usable with expire_on_commit=True.
                for obj in (appointment, business, service, customer):
                    self.session.expunge(obj)
            event_id = await self.calendar_service.sync_created_appointment(
                appointment=appointment, business=business, service=service, customer=customer,
            )
            if event_id is not None:
                async with self.session.begin():
                    await self.session.execute(
                        update(Appointment)
                        .where(Appointment.id == appointment_id, Appointment.calendar_event_id.is_(None))
                        .values(calendar_event_id=event_id)
                    )
        except (GoogleCalendarError, SQLAlchemyError, ValueError, LookupError) as exc:
            # A secondary integration must not prevent delivery of the committed reply.
            # Log no provider payloads, credentials, names or phone numbers.
            logger.warning("Calendar synchronization failed for appointment %s (%s)",
                           appointment_id, type(exc).__name__)

    async def _deliver(self, inbound_id):
        # A separate row lock serializes retries of the same response. No Business
        # lock is held during network calls. Each acknowledged part is committed.
        while True:
            async with self.session.begin():
                inbound = await self.repository.lock(inbound_id)
                data = inbound.payload
                index = data["sent_count"]
                if index >= len(data["responses"]):
                    return
                await self.client.send_text(inbound.phone, data["responses"][index])
                inbound.payload = {**data, "sent_count": index + 1}
