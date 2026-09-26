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


class ServicesConfigurationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    services: list[ServiceConfiguration]


class BusinessHoursConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: int
    start_time: time | None = None
    end_time: time | None = None
    is_closed: bool = False


class BusinessHoursConfigurationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day_of_week: int
    is_open: bool
    open_time: str | None
    close_time: str | None


class BusinessHoursConfigurationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: list[BusinessHoursConfigurationResponse]


class BusinessConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    timezone: str


class BusinessConfigurationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    timezone: str


class ServicesConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    services: list[ServiceConfiguration]


class BusinessHoursConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: list[BusinessHoursConfiguration]
