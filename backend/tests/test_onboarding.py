from datetime import datetime, time, timedelta, timezone

import pytest

from test_booking import booking_client  # noqa: F401

from app.models import (
    Business,
    BusinessHours,
    GoogleCalendarConnection,
)
from app.services.onboarding import (
    OnboardingBusinessNotFoundError,
    OnboardingIncompleteError,
    OnboardingService,
)


async def get_status(sessions, business_id=1):
    async with sessions() as session:
        return await OnboardingService(session).get_status(
            business_id
        )


async def test_unknown_business_has_no_onboarding_status(
    booking_client,
):
    _, sessions, _ = booking_client

    with pytest.raises(
        OnboardingBusinessNotFoundError,
        match="Business not found",
    ):
        await get_status(sessions, 999)


async def test_existing_business_starts_incomplete(
    booking_client,
):
    _, sessions, _ = booking_client

    status = await get_status(sessions)

    assert status.model_dump() == {
        "completed": False,
        "ready": False,
        "steps": {
            "business": True,
            "services": True,
            "hours": False,
            "calendar": False,
        },
    }


async def test_business_step_requires_name_and_valid_timezone(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions.begin() as session:
        business = await session.get(Business, 1)
        business.name = "   "
        business.timezone = "Not/A_Timezone"

    status = await get_status(sessions)

    assert status.steps.business is False
    assert status.ready is False


async def test_all_required_steps_can_be_ready_without_calendar(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions.begin() as session:
        business = await session.get(Business, 1)
        business.onboarding_completed_at = datetime(
            2026,
            9,
            25,
            12,
            tzinfo=timezone.utc,
        )
        for weekday in range(5):
            session.add(
                BusinessHours(
                    business_id=1,
                    weekday=weekday,
                    start_time=time(9),
                    end_time=time(18),
                    is_closed=False,
                )
            )

    status = await get_status(sessions)

    assert status.completed is True
    assert status.ready is True
    assert status.steps.business is True
    assert status.steps.services is True
    assert status.steps.hours is True
    assert status.steps.calendar is False


async def test_calendar_connection_does_not_complete_onboarding(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions.begin() as session:
        session.add(
            GoogleCalendarConnection(
                business_id=1,
                calendar_id="primary",
                encrypted_refresh_token="encrypted-token",
                scopes=["calendar.events"],
            )
        )

    status = await get_status(sessions)

    assert status.completed is False
    assert status.ready is False
    assert status.steps.calendar is True


async def test_complete_onboarding_reports_missing_steps_without_writing(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions() as session:
        service = OnboardingService(session)
        with pytest.raises(OnboardingIncompleteError) as error:
            await service.complete_onboarding(1)

    assert error.value.missing_steps == ("hours",)
    async with sessions() as session:
        business = await session.get(Business, 1)
        assert business.onboarding_completed_at is None


async def test_complete_onboarding_without_calendar(
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
        for weekday in range(5):
            session.add(
                BusinessHours(
                    business_id=1,
                    weekday=weekday,
                    start_time=time(9),
                    end_time=time(18),
                    is_closed=False,
                )
            )

    async with sessions() as session:
        status = await OnboardingService(
            session,
            clock=lambda: completed_at,
        ).complete_onboarding(1)

    assert status.completed is True
    assert status.ready is True
    assert status.steps.calendar is False
    async with sessions() as session:
        business = await session.get(Business, 1)
        assert business.onboarding_completed_at.replace(
            tzinfo=timezone.utc
        ) == completed_at


async def test_complete_onboarding_is_idempotent(
    booking_client,
):
    _, sessions, _ = booking_client
    original = datetime(
        2026,
        9,
        25,
        15,
        tzinfo=timezone.utc,
    )

    async with sessions.begin() as session:
        business = await session.get(Business, 1)
        business.onboarding_completed_at = original

    async with sessions() as session:
        status = await OnboardingService(
            session,
            clock=lambda: original + timedelta(days=1),
        ).complete_onboarding(1)

    assert status.completed is True
    assert status.ready is False
    async with sessions() as session:
        business = await session.get(Business, 1)
        assert business.onboarding_completed_at.replace(
            tzinfo=timezone.utc
        ) == original


async def test_complete_unknown_business_raises_domain_error(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions() as session:
        with pytest.raises(OnboardingBusinessNotFoundError):
            await OnboardingService(session).complete_onboarding(999)
