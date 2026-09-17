from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.repositories.dashboard import DashboardRepository
from app.schemas.dashboard import (
    DashboardAppointment, DashboardCustomerInfo, DashboardResponse,
    DashboardServiceInfo, DashboardSummary,
)
from app.services.booking.availability import NotFoundError


class DashboardService:
    def __init__(self, repository: DashboardRepository):
        self.repository = repository

    async def get_dashboard(self, business_id: int, day: date) -> DashboardResponse:
        business = await self.repository.business(business_id)
        if business is None:
            raise NotFoundError("Business not found")
        zone = ZoneInfo(business.timezone)
        # Build both LOCAL midnights independently: DST days need not be 24h.
        try:
            start = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
            end = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
        except OverflowError:
            raise ValueError("Date outside supported calendar range") from None
        rows = await self.repository.appointments(business_id, start, end)
        appointments = [DashboardAppointment(
            id=row["id"], starts_at=row["starts_at"].astimezone(zone),
            ends_at=row["ends_at"].astimezone(zone), status=row["status"],
            service=DashboardServiceInfo(id=row["service_id"], name=row["service_name"]),
            customer=DashboardCustomerInfo(id=row["customer_id"], name=row["customer_name"])
                     if row["customer_id"] is not None else None,
            calendar_synced=row["calendar_synced"], reminder_sent=row["reminder_sent"],
        ) for row in rows]
        return DashboardResponse(date=day, timezone=business.timezone,
            summary=DashboardSummary(
                total=len(appointments),
                confirmed=sum(a.status == "CONFIRMED" for a in appointments),
                cancelled=sum(a.status == "CANCELLED" for a in appointments),
            ), appointments=appointments)
