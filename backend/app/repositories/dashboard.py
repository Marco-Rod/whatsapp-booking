from datetime import datetime

from sqlalchemy import and_, case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, AppointmentReminder, Business, Customer, Service


class DashboardRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def business(self, business_id: int) -> Business | None:
        return await self.session.get(Business, business_id)

    async def appointments(self, business_id: int, start: datetime, end: datetime):
        sent = select(AppointmentReminder.id).where(
            AppointmentReminder.appointment_id == Appointment.id,
            AppointmentReminder.sent_at.is_not(None),
        ).exists()
        query = (select(
            Appointment.id, Appointment.starts_at, Appointment.ends_at, Appointment.status,
            Service.id.label("service_id"), Service.name.label("service_name"),
            Customer.id.label("customer_id"),
            case((Customer.name == Customer.phone, "Sin nombre"), else_=Customer.name).label("customer_name"),
            Appointment.calendar_event_id.is_not(None).label("calendar_synced"),
            sent.label("reminder_sent"),
        ).join(Service, and_(Service.id == Appointment.service_id, Service.business_id == business_id))
         .outerjoin(Customer, and_(Customer.id == Appointment.customer_id, Customer.business_id == business_id))
         .where(Appointment.business_id == business_id,
                Appointment.status.in_(["CONFIRMED", "CANCELLED"]),
                Appointment.starts_at >= start, Appointment.starts_at < end)
         .order_by(Appointment.starts_at, Appointment.id))
        return (await self.session.execute(query)).mappings().all()
