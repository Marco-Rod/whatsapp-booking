from datetime import datetime
from typing import Annotated, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    phone: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\+[1-9][0-9]{7,14}$")]


class AppointmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    business_id: int = Field(gt=0)
    service_id: int = Field(gt=0)
    customer: CustomerInput
    starts_at: AwareDatetime


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    phone: str


class AppointmentResponse(BaseModel):
    id: int
    business_id: int
    service_id: int
    customer: CustomerResponse
    starts_at: datetime
    ends_at: datetime
    status: Literal["pending", "confirmed", "cancelled", "completed"]
