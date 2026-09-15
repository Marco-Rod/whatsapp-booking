from sqlalchemy import select
from app.models import Business, InboundMessage


class InboundMessageRepository:
    def __init__(self, session):
        self.session = session

    async def business_ids(self, phone):
        return list(await self.session.scalars(select(Business.id).where(Business.phone_number == phone)))

    async def find(self, business_id, external_message_id):
        return await self.session.scalar(select(InboundMessage).where(
            InboundMessage.business_id == business_id,
            InboundMessage.external_message_id == external_message_id))

    async def add(self, business_id, message):
        inbound = InboundMessage(business_id=business_id, external_message_id=message.external_message_id,
            phone=message.phone, payload={"message": message.model_dump(), "responses": [], "sent_count": 0})
        self.session.add(inbound)
        await self.session.flush()
        return inbound

    async def lock(self, inbound_id):
        return await self.session.scalar(select(InboundMessage).where(InboundMessage.id == inbound_id)
            .with_for_update().execution_options(populate_existing=True))
