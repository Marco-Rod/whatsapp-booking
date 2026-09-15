from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Appointment, Business, Service


class BookingRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def lock_business(self, business_id: int) -> Business | None:
        # One agenda per business. Serialize booking writes until commit/rollback.
        return await self.session.scalar(select(Business).where(
            Business.id == business_id).with_for_update())

    async def service(self, business_id: int, service_id: int) -> Service | None:
        return await self.session.scalar(select(Service).where(
            Service.id == service_id, Service.business_id == business_id))

    async def add(self, appointment: Appointment) -> Appointment:
        self.session.add(appointment)
        await self.session.flush()
        return appointment
