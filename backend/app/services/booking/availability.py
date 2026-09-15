from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.schemas.availability import AvailableSlot, AvailabilityResponse, ServiceSummary


class NotFoundError(Exception):
    pass


def generate_slots(opening, closing, duration_minutes, interval_minutes, busy):
    if duration_minutes <= 0 or interval_minutes <= 0:
        raise ValueError("Duration and interval must be positive")
    # Work in UTC so elapsed durations remain correct across DST changes.
    zone = opening.tzinfo
    start = opening.astimezone(timezone.utc)
    limit = closing.astimezone(timezone.utc)
    slots = []
    while start + timedelta(minutes=duration_minutes) <= limit:
        end = start + timedelta(minutes=duration_minutes)
        if not any(start < b and end > a for a, b in busy):
            slots.append(AvailableSlot(starts_at=start.astimezone(zone), ends_at=end.astimezone(zone)))
        start += timedelta(minutes=interval_minutes)
    return slots


class AvailabilityService:
    def __init__(self, repository, interval_minutes=30):
        self.repository = repository
        self.interval_minutes = interval_minutes

    async def get_available_slots(self, business_id: int, service_id: int, target_date: date):
        business = await self.repository.business(business_id)
        if business is None:
            raise NotFoundError("Business not found")
        service = await self.repository.service(business_id, service_id)
        if service is None:
            raise NotFoundError("Active service not found for this business")
        response = AvailabilityResponse(business_id=business_id, date=target_date,
            timezone=business.timezone, service=ServiceSummary.model_validate(service), slots=[])
        hours = await self.repository.hours(business_id, target_date.weekday())
        if hours is None or hours.is_closed:
            return response
        zone = ZoneInfo(business.timezone)
        opening = datetime.combine(target_date, hours.start_time, zone)
        closing = datetime.combine(target_date, hours.end_time, zone)
        busy = await self.repository.busy(business_id, opening.astimezone(timezone.utc), closing.astimezone(timezone.utc))
        response.slots = generate_slots(opening, closing, service.duration_minutes, self.interval_minutes, busy)
        return response
