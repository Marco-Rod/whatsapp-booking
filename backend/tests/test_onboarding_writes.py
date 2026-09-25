from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select

from test_booking import booking_client  # noqa: F401

from app.models import Appointment, Business, BusinessHours, Service
from app.schemas.onboarding import (
    BusinessHoursConfiguration,
    ServiceConfiguration,
)
from app.services.onboarding import (
    OnboardingConfigurationError,
    OnboardingService,
)


def weekly_hours() -> list[BusinessHoursConfiguration]:
    return [
        BusinessHoursConfiguration(
            weekday=weekday,
            start_time=time(9),
            end_time=time(18),
        )
        for weekday in range(6)
    ] + [
        BusinessHoursConfiguration(
            weekday=6,
            is_closed=True,
        )
    ]


async def test_configure_business_updates_only_allowed_fields(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions() as session:
        result = await OnboardingService(
            session
        ).configure_business(
            1,
            name="  Nuevo Estudio  ",
            timezone_name="America/Mexico_City",
        )

        assert result.name == "Nuevo Estudio"

    async with sessions() as session:
        business = await session.get(Business, 1)
        assert business.name == "Nuevo Estudio"
        assert business.timezone == "America/Mexico_City"
        assert business.phone_number is None
        assert business.onboarding_completed_at is None


async def test_invalid_timezone_does_not_modify_business(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions() as session:
        with pytest.raises(
            OnboardingConfigurationError,
            match="timezone",
        ):
            await OnboardingService(session).configure_business(
                1,
                name="Changed",
                timezone_name="Not/A_Timezone",
            )

    async with sessions() as session:
        business = await session.get(Business, 1)
        assert business.name == "One"
        assert business.timezone == "America/Mexico_City"


async def test_replace_services_updates_creates_and_deactivates(
    booking_client,
):
    _, sessions, _ = booking_client
    start = datetime(2026, 9, 25, 15, tzinfo=timezone.utc)
    async with sessions.begin() as session:
        appointment = Appointment(
            business_id=1,
            service_id=1,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            status="CONFIRMED",
        )
        session.add(appointment)
        await session.flush()
        appointment_id = appointment.id

    async with sessions() as session:
        configured = await OnboardingService(
            session
        ).replace_services(
            1,
            [
                ServiceConfiguration(
                    name="Color",
                    duration_minutes=90,
                )
            ],
        )
        new_service_id = configured[0].id

    async with sessions() as session:
        old_service = await session.get(Service, 1)
        new_service = await session.get(Service, new_service_id)
        appointment = await session.get(
            Appointment,
            appointment_id,
        )
        assert old_service.is_active is False
        assert new_service.is_active is True
        assert new_service.name == "Color"
        assert new_service.duration_minutes == 90
        assert appointment.service_id == old_service.id


async def test_replace_services_reactivates_and_updates_existing(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions.begin() as session:
        service = await session.get(Service, 1)
        service.is_active = False

    async with sessions() as session:
        configured = await OnboardingService(
            session
        ).replace_services(
            1,
            [
                ServiceConfiguration(
                    name="Cut",
                    duration_minutes=75,
                )
            ],
        )

    assert configured[0].id == 1
    async with sessions() as session:
        service = await session.get(Service, 1)
        assert service.is_active is True
        assert service.duration_minutes == 75


@pytest.mark.parametrize(
    "services",
    [
        [],
        [ServiceConfiguration(name="", duration_minutes=30)],
        [ServiceConfiguration(name="Color", duration_minutes=0)],
        [
            ServiceConfiguration(name="Color", duration_minutes=30),
            ServiceConfiguration(name=" color ", duration_minutes=60),
        ],
    ],
    ids=["empty", "blank-name", "zero-duration", "duplicate-name"],
)
async def test_invalid_services_leave_existing_state_untouched(
    booking_client,
    services,
):
    _, sessions, _ = booking_client

    async with sessions() as session:
        with pytest.raises(OnboardingConfigurationError):
            await OnboardingService(session).replace_services(
                1,
                services,
            )

    async with sessions() as session:
        existing = list(
            await session.scalars(
                select(Service).where(Service.business_id == 1)
            )
        )
        assert [(row.name, row.duration_minutes, row.is_active) for row in existing] == [
            ("Cut", 60, True),
            ("Inactive", 60, False),
            ("Long", 120, True),
        ]


async def test_replace_business_hours_upserts_full_week(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions() as session:
        configured = await OnboardingService(
            session
        ).replace_business_hours(1, weekly_hours())

    assert [row.weekday for row in configured] == list(range(7))
    async with sessions() as session:
        rows = list(
            await session.scalars(
                select(BusinessHours)
                .where(BusinessHours.business_id == 1)
                .order_by(BusinessHours.weekday)
            )
        )
        assert len(rows) == 7
        assert rows[0].start_time == time(9)
        assert rows[0].end_time == time(18)
        assert rows[0].is_closed is False
        assert rows[6].is_closed is True
        assert rows[6].start_time is None
        assert rows[6].end_time is None


@pytest.mark.parametrize(
    "hours",
    [
        weekly_hours()[:-1],
        weekly_hours()[:-1] + [
            BusinessHoursConfiguration(
                weekday=5,
                is_closed=True,
            )
        ],
        [
            BusinessHoursConfiguration(
                weekday=weekday,
                is_closed=(weekday == 6),
            )
            for weekday in range(7)
        ],
        [
            BusinessHoursConfiguration(
                weekday=weekday,
                start_time=time(18),
                end_time=time(9),
            )
            for weekday in range(7)
        ],
        [
            BusinessHoursConfiguration(
                weekday=weekday,
                start_time=time(9),
                end_time=time(9),
            )
            for weekday in range(7)
        ],
    ],
    ids=[
        "six-days",
        "duplicate-weekday",
        "open-without-times",
        "reversed-range",
        "equal-range",
    ],
)
async def test_invalid_hours_leave_existing_state_untouched(
    booking_client,
    hours,
):
    _, sessions, _ = booking_client

    async with sessions() as session:
        with pytest.raises(OnboardingConfigurationError):
            await OnboardingService(
                session
            ).replace_business_hours(1, hours)

    async with sessions() as session:
        rows = list(
            await session.scalars(
                select(BusinessHours)
                .where(BusinessHours.business_id == 1)
                .order_by(BusinessHours.weekday)
            )
        )
        assert [row.weekday for row in rows] == [5, 6]
        assert rows[0].start_time == time(9)
        assert rows[0].end_time == time(18)
        assert rows[1].is_closed is True


async def test_configuration_writes_preserve_completion_timestamp(
    booking_client,
):
    _, sessions, _ = booking_client
    completed_at = datetime(
        2026,
        9,
        25,
        15,
        tzinfo=timezone.utc,
    )
    async with sessions.begin() as session:
        business = await session.get(Business, 1)
        business.onboarding_completed_at = completed_at

    async with sessions() as session:
        await OnboardingService(session).configure_business(
            1,
            name="One",
            timezone_name="America/Mexico_City",
        )
    async with sessions() as session:
        await OnboardingService(session).replace_services(
            1,
            [
                ServiceConfiguration(
                    name="Cut",
                    duration_minutes=60,
                )
            ],
        )
    async with sessions() as session:
        await OnboardingService(session).replace_business_hours(
            1,
            weekly_hours(),
        )

    async with sessions() as session:
        business = await session.get(Business, 1)
        assert business.onboarding_completed_at.replace(
            tzinfo=timezone.utc
        ) == completed_at
