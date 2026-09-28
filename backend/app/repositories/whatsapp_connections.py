from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WhatsAppConnection


class WhatsAppConnectionRepository:
    """Persistence operations for the private, per-business WhatsApp link."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_business_id(
        self,
        business_id: int,
    ) -> WhatsAppConnection | None:
        return await self.session.scalar(
            select(WhatsAppConnection).where(
                WhatsAppConnection.business_id == business_id
            )
        )

    async def get_by_phone_number_id(
        self,
        phone_number_id: str,
    ) -> WhatsAppConnection | None:
        return await self.session.scalar(
            select(WhatsAppConnection).where(
                WhatsAppConnection.phone_number_id == phone_number_id
            )
        )
