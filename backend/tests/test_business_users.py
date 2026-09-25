import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from test_booking import booking_client  # noqa: F401

from app.models import Business, BusinessUser


def make_user(
    *,
    business_id=1,
    subject="google-subject-1",
    email="owner@example.com",
    display_name="Owner",
):
    return BusinessUser(
        business_id=business_id,
        email=email,
        display_name=display_name,
        auth_provider="google",
        provider_subject=subject,
    )


async def test_provider_subject_is_unique_per_provider(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions.begin() as session:
        session.add(make_user())

    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            session.add(
                make_user(
                    business_id=2,
                    email="other@example.com",
                )
            )


async def test_same_subject_can_exist_for_different_provider(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions.begin() as session:
        session.add(make_user())
        session.add(
            BusinessUser(
                business_id=2,
                email="owner@example.com",
                display_name="Owner",
                auth_provider="future-provider",
                provider_subject="google-subject-1",
            )
        )

    async with sessions() as session:
        users = list(await session.scalars(select(BusinessUser)))
        assert len(users) == 2


async def test_multiple_users_can_administer_same_business(
    booking_client,
):
    _, sessions, _ = booking_client

    async with sessions.begin() as session:
        session.add_all(
            [
                make_user(),
                make_user(
                    subject="google-subject-2",
                    email="reception@example.com",
                    display_name="Reception",
                ),
            ]
        )

    async with sessions() as session:
        users = list(
            await session.scalars(
                select(BusinessUser).where(
                    BusinessUser.business_id == 1
                )
            )
        )
        assert {user.provider_subject for user in users} == {
            "google-subject-1",
            "google-subject-2",
        }


async def test_email_does_not_determine_identity(booking_client):
    _, sessions, _ = booking_client

    async with sessions.begin() as session:
        session.add_all(
            [
                make_user(subject="google-subject-1"),
                make_user(
                    business_id=2,
                    subject="google-subject-2",
                ),
            ]
        )

    async with sessions() as session:
        users = list(
            await session.scalars(
                select(BusinessUser).where(
                    BusinessUser.email == "owner@example.com"
                )
            )
        )
        assert len(users) == 2
        assert {user.business_id for user in users} == {1, 2}


async def test_deleting_business_deletes_its_users(booking_client):
    _, sessions, _ = booking_client

    async with sessions.begin() as session:
        session.add(make_user())

    async with sessions.begin() as session:
        business = await session.scalar(
            select(Business)
            .where(Business.id == 1)
            .options(selectinload(Business.users))
        )
        await session.delete(business)

    async with sessions() as session:
        assert await session.scalar(
            select(BusinessUser).where(
                BusinessUser.business_id == 1
            )
        ) is None


def test_business_user_has_no_google_token_columns():
    columns = {
        column.key
        for column in inspect(BusinessUser).columns
    }

    assert columns == {
        "id",
        "business_id",
        "email",
        "display_name",
        "auth_provider",
        "provider_subject",
        "created_at",
        "updated_at",
    }
    assert not {
        "id_token",
        "access_token",
        "refresh_token",
        "scopes",
        "password",
    } & columns
