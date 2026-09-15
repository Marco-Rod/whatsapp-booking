from sqlalchemy import select
from app.models import Conversation, Service


class ConversationRepository:
    def __init__(self, session):
        self.session = session

    async def get_or_create(self, business_id, phone):
        # Caller must hold the Business lock before reading or creating state.
        conversation = await self.session.scalar(select(Conversation).where(
            Conversation.business_id == business_id, Conversation.phone == phone)
            .execution_options(populate_existing=True))
        if conversation is None:
            conversation = Conversation(business_id=business_id, phone=phone, state="main_menu", context={})
            self.session.add(conversation)
            await self.session.flush()
        return conversation

    async def active_services(self, business_id):
        return list(await self.session.scalars(select(Service).where(
            Service.business_id == business_id, Service.is_active.is_(True)).order_by(Service.id)))
