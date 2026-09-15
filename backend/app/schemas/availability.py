from datetime import date, datetime
from pydantic import BaseModel, ConfigDict


class AvailableSlot(BaseModel):
    starts_at: datetime
    ends_at: datetime


class ServiceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    duration_minutes: int


class AvailabilityResponse(BaseModel):
    business_id: int
    date: date
    timezone: str
    service: ServiceSummary
    slots: list[AvailableSlot]
