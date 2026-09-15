from datetime import datetime, timezone
from hmac import compare_digest

from app.integrations.whatsapp.client import WhatsAppConfigurationError
from app.integrations.whatsapp.parser import parse_messages
from app.repositories.booking import BookingRepository
from app.repositories.inbound_messages import InboundMessageRepository
from app.services.conversation.engine import ConversationEngine


def verify_webhook(config, mode, token, challenge):
    expected = config.whatsapp_verify_token.get_secret_value()
    if not expected:
        raise WhatsAppConfigurationError("Webhook verification is not configured")
    if mode != "subscribe" or not token or not compare_digest(token.encode(), expected.encode()):
        raise PermissionError("Invalid verification token")
    return challenge


class WebhookService:
    def __init__(self, session, client, config, engine=None):
        self.session = session
        self.client = client
        self.config = config
        self.repository = InboundMessageRepository(session)
        self.engine = engine or ConversationEngine(session)

    async def process(self, payload):
        messages = parse_messages(payload)
        for message in messages:
            if not self.config.whatsapp_phone_number_id:
                raise WhatsAppConfigurationError("WhatsApp receiving number is not configured")
            if message.phone_number_id != self.config.whatsapp_phone_number_id:
                continue
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
                    # Store replies in the same commit as conversation/booking. Split long menus.
                    responses = [text[i:i + 4096] for text in result.messages for i in range(0, len(text), 4096)]
                    inbound.payload = {**inbound.payload, "responses": responses, "sent_count": 0}
                    inbound.processed_at = datetime.now(timezone.utc)
                inbound_id = inbound.id
            await self._deliver(inbound_id)

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
