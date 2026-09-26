from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Business,
    BusinessHours,
    GoogleCalendarConnection,
    Service,
)
from app.schemas.onboarding import (
    BusinessConfigurationResponse,
    BusinessHoursConfiguration,
    BusinessHoursConfigurationListResponse,
    BusinessHoursConfigurationResponse,
    OnboardingStatus,
    OnboardingSteps,
    ServiceConfiguration,
    ServicesConfigurationResponse,
)


class OnboardingBusinessNotFoundError(LookupError):
    pass


class OnboardingIncompleteError(ValueError):
    def __init__(self, missing_steps: list[str]) -> None:
        self.missing_steps = tuple(missing_steps)
        super().__init__(
            "Missing onboarding steps: "
            + ", ".join(self.missing_steps)
        )


class OnboardingConfigurationError(ValueError):
    pass


class OnboardingService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.clock = clock or (
            lambda: datetime.now(timezone.utc)
        )

    async def get_status(self, business_id: int) -> OnboardingStatus:
        business = await self.session.get(Business, business_id)

        if business is None:
            raise OnboardingBusinessNotFoundError(
                "Business not found"
            )

        return await self._status_for(business)

    async def get_business_configuration(
        self,
        business_id: int,
    ) -> BusinessConfigurationResponse:
        business = await self.session.get(Business, business_id)

        if business is None:
            raise OnboardingBusinessNotFoundError(
                "Business not found"
            )

        return BusinessConfigurationResponse(
            name=business.name,
            timezone=business.timezone,
        )

    async def get_services_configuration(
        self,
        business_id: int,
    ) -> ServicesConfigurationResponse:
        business = await self.session.get(Business, business_id)

        if business is None:
            raise OnboardingBusinessNotFoundError(
                "Business not found"
            )

        services = await self.session.scalars(
            select(Service)
            .where(
                Service.business_id == business_id,
                Service.is_active.is_(True),
            )
            .order_by(Service.id)
        )

        return ServicesConfigurationResponse(
            services=[
                ServiceConfiguration(
                    name=service.name,
                    duration_minutes=service.duration_minutes,
                )
                for service in services
            ]
        )

    async def get_business_hours_configuration(
        self,
        business_id: int,
    ) -> BusinessHoursConfigurationListResponse:
        business = await self.session.get(Business, business_id)

        if business is None:
            raise OnboardingBusinessNotFoundError(
                "Business not found"
            )

        configured_hours = {
            row.weekday: row
            for row in await self.session.scalars(
                select(BusinessHours).where(
                    BusinessHours.business_id == business_id
                )
            )
        }
        hours = []
        for weekday in range(7):
            row = configured_hours.get(weekday)
            is_open = row is not None and not row.is_closed
            hours.append(
                BusinessHoursConfigurationResponse(
                    day_of_week=weekday,
                    is_open=is_open,
                    open_time=(
                        row.start_time.strftime("%H:%M")
                        if is_open and row.start_time is not None
                        else None
                    ),
                    close_time=(
                        row.end_time.strftime("%H:%M")
                        if is_open and row.end_time is not None
                        else None
                    ),
                )
            )

        return BusinessHoursConfigurationListResponse(hours=hours)

    async def complete_onboarding(
        self,
        business_id: int,
    ) -> OnboardingStatus:
        async with self.session.begin():
            business = await self.session.get(
                Business,
                business_id,
                with_for_update=True,
            )

            if business is None:
                raise OnboardingBusinessNotFoundError(
                    "Business not found"
                )

            status = await self._status_for(business)

            if status.completed:
                return status

            missing_steps = [
                name
                for name in ("business", "services", "hours")
                if not getattr(status.steps, name)
            ]

            if missing_steps:
                raise OnboardingIncompleteError(
                    missing_steps
                )

            completed_at = self.clock()
            if completed_at.utcoffset() is None:
                raise ValueError(
                    "Onboarding clock must include a timezone"
                )

            business.onboarding_completed_at = (
                completed_at.astimezone(timezone.utc)
            )

            return status.model_copy(
                update={"completed": True}
            )

    async def configure_business(
        self,
        business_id: int,
        *,
        name: str,
        timezone_name: str,
    ) -> Business:
        normalized_name = name.strip()
        normalized_timezone = timezone_name.strip()

        if not normalized_name or len(normalized_name) > 200:
            raise OnboardingConfigurationError(
                "Business name is invalid"
            )

        if (
            not normalized_timezone
            or len(normalized_timezone) > 100
            or not self._timezone_is_valid(normalized_timezone)
        ):
            raise OnboardingConfigurationError(
                "Business timezone is invalid"
            )

        async with self.session.begin():
            business = await self._lock_business(business_id)
            business.name = normalized_name
            business.timezone = normalized_timezone
            return business

    async def replace_services(
        self,
        business_id: int,
        services: Sequence[ServiceConfiguration],
    ) -> list[Service]:
        validated = self._validate_services(services)

        async with self.session.begin():
            await self._lock_business(business_id)
            existing = list(
                await self.session.scalars(
                    select(Service).where(
                        Service.business_id == business_id
                    )
                )
            )
            by_name: dict[str, Service] = {}
            for service in existing:
                key = service.name.strip().casefold()
                if key in by_name:
                    raise OnboardingConfigurationError(
                        "Existing service names are duplicated"
                    )
                by_name[key] = service

            configured = []
            desired_names = set()
            for item in validated:
                key = item.name.casefold()
                desired_names.add(key)
                service = by_name.get(key)
                if service is None:
                    service = Service(
                        business_id=business_id,
                        name=item.name,
                        duration_minutes=item.duration_minutes,
                        is_active=True,
                    )
                    self.session.add(service)
                else:
                    service.name = item.name
                    service.duration_minutes = (
                        item.duration_minutes
                    )
                    service.is_active = True
                configured.append(service)

            for key, service in by_name.items():
                if key not in desired_names:
                    service.is_active = False

            await self.session.flush()
            return configured

    async def replace_business_hours(
        self,
        business_id: int,
        hours: Sequence[BusinessHoursConfiguration],
    ) -> list[BusinessHours]:
        validated = self._validate_hours(hours)

        async with self.session.begin():
            await self._lock_business(business_id)
            existing = {
                row.weekday: row
                for row in await self.session.scalars(
                    select(BusinessHours).where(
                        BusinessHours.business_id == business_id
                    )
                )
            }
            configured = []
            for item in validated:
                row = existing.get(item.weekday)
                if row is None:
                    row = BusinessHours(
                        business_id=business_id,
                        weekday=item.weekday,
                    )
                    self.session.add(row)
                row.is_closed = item.is_closed
                row.start_time = (
                    None if item.is_closed else item.start_time
                )
                row.end_time = (
                    None if item.is_closed else item.end_time
                )
                configured.append(row)

            await self.session.flush()
            return configured

    async def _lock_business(self, business_id: int) -> Business:
        business = await self.session.get(
            Business,
            business_id,
            with_for_update=True,
        )
        if business is None:
            raise OnboardingBusinessNotFoundError(
                "Business not found"
            )
        return business

    @staticmethod
    def _validate_services(
        services: Sequence[ServiceConfiguration],
    ) -> list[ServiceConfiguration]:
        if not services:
            raise OnboardingConfigurationError(
                "At least one service is required"
            )

        validated = []
        names = set()
        for item in services:
            name = item.name.strip()
            if not name or len(name) > 200:
                raise OnboardingConfigurationError(
                    "Service name is invalid"
                )
            if (
                isinstance(item.duration_minutes, bool)
                or item.duration_minutes <= 0
            ):
                raise OnboardingConfigurationError(
                    "Service duration must be positive"
                )
            key = name.casefold()
            if key in names:
                raise OnboardingConfigurationError(
                    "Service names must be unique"
                )
            names.add(key)
            validated.append(
                ServiceConfiguration(
                    name=name,
                    duration_minutes=item.duration_minutes,
                )
            )
        return validated

    @staticmethod
    def _validate_hours(
        hours: Sequence[BusinessHoursConfiguration],
    ) -> list[BusinessHoursConfiguration]:
        if len(hours) != 7:
            raise OnboardingConfigurationError(
                "Exactly seven weekdays are required"
            )

        weekdays = [item.weekday for item in hours]
        if set(weekdays) != set(range(7)):
            raise OnboardingConfigurationError(
                "Weekdays must contain 0 through 6 exactly once"
            )

        validated = []
        for item in hours:
            if item.is_closed:
                validated.append(
                    BusinessHoursConfiguration(
                        weekday=item.weekday,
                        is_closed=True,
                    )
                )
                continue

            if (
                item.start_time is None
                or item.end_time is None
                or item.start_time >= item.end_time
            ):
                raise OnboardingConfigurationError(
                    "Open days require a valid time range"
                )
            validated.append(item)

        return sorted(
            validated,
            key=lambda item: item.weekday,
        )

    async def _status_for(
        self,
        business: Business,
    ) -> OnboardingStatus:
        business_id = business.id
        service_exists = (
            await self.session.scalar(
                select(Service.id).where(
                    Service.business_id == business_id,
                    Service.is_active.is_(True),
                ).limit(1)
            )
            is not None
        )

        configured_weekdays = set(
            await self.session.scalars(
                select(BusinessHours.weekday).where(
                    BusinessHours.business_id == business_id
                )
            )
        )

        calendar_exists = (
            await self.session.scalar(
                select(GoogleCalendarConnection.id).where(
                    GoogleCalendarConnection.business_id
                    == business_id
                )
            )
            is not None
        )

        steps = OnboardingSteps(
            business=self._business_is_configured(business),
            services=service_exists,
            hours=configured_weekdays == set(range(7)),
            calendar=calendar_exists,
        )

        return OnboardingStatus(
            completed=(
                business.onboarding_completed_at is not None
            ),
            ready=(
                steps.business
                and steps.services
                and steps.hours
            ),
            steps=steps,
        )

    @staticmethod
    def _business_is_configured(business: Business) -> bool:
        if not business.name.strip():
            return False

        return OnboardingService._timezone_is_valid(
            business.timezone
        )

    @staticmethod
    def _timezone_is_valid(timezone_name: str) -> bool:
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            return False

        return True
