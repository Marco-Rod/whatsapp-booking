from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class DashboardSummary(BaseModel):
    total: int
    confirmed: int
    cancelled: int


class DashboardServiceInfo(BaseModel):
    id: int
    name: str


class DashboardCustomerInfo(BaseModel):
    id: int
    name: str


class DashboardAppointment(BaseModel):
    id: int
    starts_at: datetime
    ends_at: datetime
    status: Literal["CONFIRMED", "CANCELLED"]
    service: DashboardServiceInfo
    customer: DashboardCustomerInfo | None
    calendar_synced: bool
    reminder_sent: bool


class DashboardResponse(BaseModel):
    date: date
    timezone: str
    summary: DashboardSummary
    appointments: list[DashboardAppointment]
