from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
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

    async def appointment_business_id(self, appointment_id: int) -> int | None:
        return await self.session.scalar(select(Appointment.business_id).where(Appointment.id == appointment_id))

    async def appointment(self, appointment_id: int) -> Appointment | None:
        return await self.session.scalar(select(Appointment).where(Appointment.id == appointment_id)
            .options(selectinload(Appointment.customer)).execution_options(populate_existing=True))
