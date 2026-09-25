from datetime import time

from pydantic import BaseModel, ConfigDict


class OnboardingSteps(BaseModel):
    business: bool
    services: bool
    hours: bool
    calendar: bool


class OnboardingStatus(BaseModel):
    completed: bool
    ready: bool
    steps: OnboardingSteps


class ServiceConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    duration_minutes: int


class BusinessHoursConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: int
    start_time: time | None = None
    end_time: time | None = None
    is_closed: bool = False


class BusinessConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    timezone: str


class ServicesConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    services: list[ServiceConfiguration]


class BusinessHoursConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: list[BusinessHoursConfiguration]
