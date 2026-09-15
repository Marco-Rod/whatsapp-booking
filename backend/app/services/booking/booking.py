from datetime import timezone
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models import Appointment
from app.repositories.availability import AvailabilityRepository
from app.repositories.booking import BookingRepository
from app.repositories.customers import CustomerRepository
from app.schemas.booking import AppointmentCreate, AppointmentResponse, CustomerResponse
from app.services.booking.availability import AvailabilityService, NotFoundError


class BookingConflictError(Exception):
    pass


class BookingService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.bookings = BookingRepository(session)
        self.customers = CustomerRepository(session)
        self.availability = AvailabilityService(
            AvailabilityRepository(session), settings.slot_interval_minutes)

    async def create_appointment(self, request: AppointmentCreate) -> AppointmentResponse:
        async with self.session.begin():
            business = await self.bookings.lock_business(request.business_id)
            if business is None:
                raise NotFoundError("Business not found")
            service = await self.bookings.service(business.id, request.service_id)
            if service is None:
                raise NotFoundError("Service not found for this business")
            if not service.is_active:
                raise BookingConflictError("Service is inactive")

            zone = ZoneInfo(business.timezone)
            start = request.starts_at.astimezone(timezone.utc)
            availability = await self.availability.get_available_slots(
                business.id, service.id, start.astimezone(zone).date())
            slot = next((slot for slot in availability.slots
                         if slot.starts_at.astimezone(timezone.utc) == start), None)
            if slot is None:
                raise BookingConflictError("Requested time is not available")

            customer = await self.customers.get_or_create(
                business.id, request.customer.phone, request.customer.name)
            appointment = await self.bookings.add(Appointment(
                business_id=business.id, service_id=service.id, customer_id=customer.id,
                starts_at=start, ends_at=slot.ends_at.astimezone(timezone.utc), status="CONFIRMED"))
            response = AppointmentResponse(
                id=appointment.id, business_id=business.id, service_id=service.id,
                customer=CustomerResponse.model_validate(customer),
                starts_at=slot.starts_at, ends_at=slot.ends_at, status="confirmed")
        return response
