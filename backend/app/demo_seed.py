"""Fictional fixtures only; never call Calendar or WhatsApp."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.models import Appointment, Business, BusinessHours, Customer, Service

ZONE = ZoneInfo("America/Mexico_City")
ROWS = (
    ("mariana", "Mariana", "Corte", time(9), "CONFIRMED"),
    ("sofia", "Sofía", "Manicure", time(10, 30), "CONFIRMED"),
    ("daniela", "Daniela", "Peinado", time(12), "CONFIRMED"),
    ("andrea", "Andrea", "Corte", time(15), "CANCELLED"),
    ("fernanda", "Fernanda", "Manicure", time(17), "CONFIRMED"),
)


def parse_day(value: str) -> date:
    day = datetime.now(ZONE).date() if value == "today" else date.fromisoformat(value)
    if not 1900 <= day.year <= 9998:
        raise ValueError("Usa una fecha entre 1900 y 9998")
    return day


async def seed_demo(session, day: date) -> int:
    """Own one transaction. Repeating a date preserves existing fixtures/bookings."""
    async with session.begin():
        if session.get_bind().dialect.name == "postgresql":
            # Also serialize first-run creation, before a Business row exists.
            await session.execute(text("SELECT pg_advisory_xact_lock(6062026)"))
        matches = (await session.scalars(select(Business).where(
            Business.name == "Bella Studio").with_for_update())).all()
        if len(matches) > 1:
            raise ValueError("Hay varios Bella Studio; usa una base de demo aislada.")
        business = matches[0] if matches else Business(name="Bella Studio", timezone=str(ZONE))
        session.add(business)
        await session.flush()
        if business.timezone != str(ZONE):
            raise ValueError("Bella Studio usa otra zona horaria; no se modificó su configuración.")
        services = {}
        for name in ("Corte", "Manicure", "Peinado"):
            found = (await session.scalars(select(Service).where(
                Service.business_id == business.id, Service.name == name))).all()
            if len(found) > 1:
                raise ValueError(f"Servicio duplicado: {name}; usa una base de demo aislada.")
            service = found[0] if found else Service(
                business_id=business.id, name=name, duration_minutes=60, is_active=True)
            if found and (service.duration_minutes != 60 or not service.is_active):
                raise ValueError(f"{name} debe estar activo y durar 60 minutos; no se modificó.")
            session.add(service)
            services[name] = service
        for weekday in range(7):
            hours = await session.scalar(select(BusinessHours).where(
                BusinessHours.business_id == business.id, BusinessHours.weekday == weekday))
            if hours is None:
                hours = BusinessHours(business_id=business.id, weekday=weekday,
                                      start_time=time(9), end_time=time(18), is_closed=False)
                session.add(hours)
            if weekday == day.weekday() and (hours.is_closed or hours.start_time > time(9)
                                             or hours.end_time < time(18)):
                raise ValueError("El horario existente no admite la agenda demo; usa otra fecha o base.")
        await session.flush()
        for key, name, service_name, hour, status in ROWS:
            # Deliberately not a telephone number; reserved namespace, never dialable.
            phone = f"demo:bella:{key}"
            customer = await session.scalar(select(Customer).where(
                Customer.business_id == business.id, Customer.phone == phone))
            if customer is None:
                customer = Customer(business_id=business.id, phone=phone, name=name)
                session.add(customer)
                await session.flush()
            start = datetime.combine(day, hour, ZONE).astimezone(timezone.utc)
            end = start + timedelta(hours=1)
            day_start = datetime.combine(day, time.min, ZONE).astimezone(timezone.utc)
            existing = await session.scalar(select(Appointment).where(
                Appointment.business_id == business.id, Appointment.customer_id == customer.id,
                Appointment.starts_at >= day_start, Appointment.starts_at < day_start + timedelta(days=1)))
            if existing is not None:
                continue
            conflict = await session.scalar(select(Appointment.id).where(
                Appointment.business_id == business.id,
                Appointment.status.in_(("PENDING", "CONFIRMED")),
                Appointment.starts_at < end, Appointment.ends_at > start))
            if status == "CONFIRMED" and conflict is not None:
                raise ValueError(f"Horario ocupado a las {hour:%H:%M}; no se cambió ninguna cita.")
            session.add(Appointment(business_id=business.id, customer_id=customer.id,
                service_id=services[service_name].id, starts_at=start, ends_at=end, status=status))
            await session.flush()
        return business.id
