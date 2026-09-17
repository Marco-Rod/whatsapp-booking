"""Create one real test appointment due for a reminder, without sending anything.

Run from root with backend's Python and --phone +52... . Prints the new ID for
process_reminders.py --appointment-id ID. Does not create a Calendar event.
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


async def run(phone: str) -> None:
    os.chdir(ROOT / "backend")
    from sqlalchemy import select
    from app.core.database import Session, engine
    from app.models import Business, Service
    from app.schemas.booking import AppointmentCreate, CustomerInput
    from app.services.booking.booking import BookingService
    from app.services.reminder_processor import format_reminder

    customer = CustomerInput(name="Prueba recordatorio", phone=phone)
    try:
        now = datetime.now(timezone.utc)
        async with Session() as session:
            async with session.begin():
                business = (await session.scalars(select(Business).where(Business.name == "Bella Studio"))).one()
                service = (await session.scalars(select(Service).where(
                    Service.business_id == business.id, Service.name == "Corte", Service.is_active.is_(True)))).one()
                booking = BookingService(session)
                today = now.astimezone(ZoneInfo(business.timezone)).date()
                choices = []
                for day in (today, today + timedelta(days=1)):
                    available = await booking.availability.get_available_slots(business.id, service.id, day)
                    choices.extend(slot for slot in available.slots
                                   if now + timedelta(minutes=10) < slot.starts_at <= now + timedelta(hours=24))
                if not choices:
                    raise RuntimeError("No available appointment in the next 24 hours")
                chosen = choices[0]
                business_id, service_id, service_name, zone = business.id, service.id, service.name, business.timezone
            appointment = await booking.create_appointment(AppointmentCreate(
                business_id=business_id, service_id=service_id, starts_at=chosen.starts_at, customer=customer))
        print("Appointment:", appointment.id)
        print("Start:", appointment.starts_at.isoformat())
        print(format_reminder(service_name=service_name, starts_at=appointment.starts_at, business_timezone=zone))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.phone))
