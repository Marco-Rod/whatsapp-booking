from sqlalchemy import select
from app.models import Appointment, Business, BusinessHours, Service


class AvailabilityRepository:
    def __init__(self, session):
        self.session = session

    async def business(self, business_id):
        return await self.session.get(Business, business_id)

    async def service(self, business_id, service_id):
        return await self.session.scalar(select(Service).where(
            Service.id == service_id, Service.business_id == business_id, Service.is_active.is_(True)))

    async def hours(self, business_id, weekday):
        return await self.session.scalar(select(BusinessHours).where(
            BusinessHours.business_id == business_id, BusinessHours.weekday == weekday))

    async def busy(self, business_id, start, end):
        result = await self.session.scalars(select(Appointment).where(
            Appointment.business_id == business_id,
            Appointment.status.in_(["PENDING", "CONFIRMED"]),
            Appointment.starts_at < end, Appointment.ends_at > start))
        return [(a.starts_at, a.ends_at) for a in result]
