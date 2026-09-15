from datetime import timezone
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models import Appointment
from app.repositories.availability import AvailabilityRepository
from app.repositories.booking import BookingRepository
from app.repositories.customers import CustomerRepository
from app.schemas.booking import AppointmentCreate, AppointmentReschedule, AppointmentResponse, CustomerResponse
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
            return await self.create_appointment_in_transaction(request)

    async def create_appointment_in_transaction(self, request: AppointmentCreate) -> AppointmentResponse:
        """Join an explicit caller-owned transaction; never commit independently."""
        if not self.session.in_transaction():
            raise RuntimeError("An active transaction is required")
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

    def _response(self, appointment, business):
        zone = ZoneInfo(business.timezone)
        return AppointmentResponse(
            id=appointment.id, business_id=appointment.business_id, service_id=appointment.service_id,
            customer=CustomerResponse.model_validate(appointment.customer) if appointment.customer else None,
            starts_at=appointment.starts_at.astimezone(zone), ends_at=appointment.ends_at.astimezone(zone),
            status=appointment.status.lower())

    async def _locked_appointment(self, appointment_id):
        # Read only the owner before locking. Load mutable appointment state AFTER
        # acquiring the business lock, so a waiting request sees the latest commit.
        business_id = await self.bookings.appointment_business_id(appointment_id)
        if business_id is None:
            raise NotFoundError("Appointment not found")
        business = await self.bookings.lock_business(business_id)
        appointment = await self.bookings.appointment(appointment_id)
        if business is None or appointment is None:
            raise NotFoundError("Appointment not found")
        return appointment, business

    async def get_appointment(self, appointment_id: int) -> AppointmentResponse:
        async with self.session.begin():
            appointment = await self.bookings.appointment(appointment_id)
            if appointment is None:
                raise NotFoundError("Appointment not found")
            business = await AvailabilityRepository(self.session).business(appointment.business_id)
            return self._response(appointment, business)

    async def cancel_appointment(self, appointment_id: int) -> AppointmentResponse:
        async with self.session.begin():
            appointment, business = await self._locked_appointment(appointment_id)
            if appointment.status not in ("CONFIRMED", "CANCELLED"):
                raise BookingConflictError("Only confirmed appointments can be cancelled")
            if appointment.status != "CANCELLED":
                appointment.status = "CANCELLED"
                await self.session.flush()
            response = self._response(appointment, business)
        return response

    async def reschedule_appointment(self, appointment_id: int,
                                     request: AppointmentReschedule) -> AppointmentResponse:
        async with self.session.begin():
            appointment, business = await self._locked_appointment(appointment_id)
            if appointment.status != "CONFIRMED":
                raise BookingConflictError("Only confirmed appointments can be rescheduled")
            service = await self.bookings.service(business.id, appointment.service_id)
            if service is None:
                raise NotFoundError("Service not found for this business")
            if not service.is_active:
                raise BookingConflictError("Service is inactive")
            start = request.starts_at.astimezone(timezone.utc)
            availability = await self.availability.get_available_slots(
                business.id, service.id, start.astimezone(ZoneInfo(business.timezone)).date(),
                exclude_appointment_id=appointment.id)
            slot = next((slot for slot in availability.slots
                         if slot.starts_at.astimezone(timezone.utc) == start), None)
            if slot is None:
                raise BookingConflictError("Requested time is not available")
            appointment.starts_at = start
            appointment.ends_at = slot.ends_at.astimezone(timezone.utc)
            await self.session.flush()
            response = self._response(appointment, business)
        return response
