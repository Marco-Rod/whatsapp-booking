from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from test_booking import booking_client  # noqa: F401

from app.models import Business, BusinessUser
from app.security.admin_tokens import hash_admin_token
from app.security.google_identity import (
    GoogleIdentity,
    GoogleIdentityError,
)
from app.services.google_admin_auth import (
    GoogleAdminAuthError,
    GoogleAdminAuthService,
)


ADMIN_TOKEN = "bella-admin-token"
GOOGLE_CREDENTIAL = "verified-by-google"


def identity(
    *,
    subject="google-subject-1",
    email="owner@example.com",
    display_name="Owner",
):
    return GoogleIdentity(
        subject=subject,
        email=email,
        display_name=display_name,
        email_verified=True,
    )


def verifier(result=None, *, error=None):
    verify = AsyncMock()
    if error is not None:
        verify.side_effect = error
    else:
        verify.return_value = result or identity()
    fake = AsyncMock()
    fake.verify = verify
    return fake


async def enable_admin(sessions, business_id=1, token=ADMIN_TOKEN):
    async with sessions.begin() as session:
        business = await session.get(Business, business_id)
        business.admin_token_hash = hash_admin_token(token)


async def user_count(sessions):
    async with sessions() as session:
        return await session.scalar(
            select(func.count()).select_from(BusinessUser)
        )


async def test_first_link_creates_business_user(booking_client):
    _, sessions, _ = booking_client
    await enable_admin(sessions)
    google = verifier()

    async with sessions() as session:
        result = await GoogleAdminAuthService(
            session,
            google,
        ).link_google_identity(
            admin_token=ADMIN_TOKEN,
            google_credential=GOOGLE_CREDENTIAL,
        )

    assert result.business.id == 1
    assert result.user.business_id == 1
    assert result.user.auth_provider == "google"
    assert result.user.provider_subject == "google-subject-1"
    assert result.user.email == "owner@example.com"
    assert result.user.display_name == "Owner"
    google.verify.assert_awaited_once_with(GOOGLE_CREDENTIAL)
    assert await user_count(sessions) == 1


async def test_repeated_link_is_idempotent(booking_client):
    _, sessions, _ = booking_client
    await enable_admin(sessions)

    async with sessions() as session:
        service = GoogleAdminAuthService(session, verifier())
        first = await service.link_google_identity(
            admin_token=ADMIN_TOKEN,
            google_credential=GOOGLE_CREDENTIAL,
        )
    async with sessions() as session:
        service = GoogleAdminAuthService(session, verifier())
        second = await service.link_google_identity(
            admin_token=ADMIN_TOKEN,
            google_credential=GOOGLE_CREDENTIAL,
        )

    assert first.user.id == second.user.id
    assert await user_count(sessions) == 1


async def test_repeated_link_updates_profile_not_identity(
    booking_client,
):
    _, sessions, _ = booking_client
    await enable_admin(sessions)

    async with sessions() as session:
        first = await GoogleAdminAuthService(
            session,
            verifier(),
        ).link_google_identity(
            admin_token=ADMIN_TOKEN,
            google_credential=GOOGLE_CREDENTIAL,
        )
        user_id = first.user.id

    updated = identity(
        email="new-address@example.com",
        display_name=None,
    )
    async with sessions() as session:
        result = await GoogleAdminAuthService(
            session,
            verifier(updated),
        ).link_google_identity(
            admin_token=ADMIN_TOKEN,
            google_credential=GOOGLE_CREDENTIAL,
        )

    assert result.user.id == user_id
    assert result.user.provider_subject == "google-subject-1"
    assert result.user.email == "new-address@example.com"
    assert result.user.display_name is None


async def test_invalid_admin_token_creates_no_user(booking_client):
    _, sessions, _ = booking_client
    await enable_admin(sessions)
    google = verifier()

    async with sessions() as session:
        with pytest.raises(
            GoogleAdminAuthError,
            match="^Invalid Google admin authentication$",
        ):
            await GoogleAdminAuthService(
                session,
                google,
            ).link_google_identity(
                admin_token="wrong-token",
                google_credential=GOOGLE_CREDENTIAL,
            )

    google.verify.assert_not_awaited()
    assert await user_count(sessions) == 0


async def test_invalid_google_credential_creates_no_user(
    booking_client,
):
    _, sessions, _ = booking_client
    await enable_admin(sessions)
    google = verifier(error=GoogleIdentityError("internal detail"))

    async with sessions() as session:
        with pytest.raises(
            GoogleAdminAuthError,
            match="^Invalid Google admin authentication$",
        ):
            await GoogleAdminAuthService(
                session,
                google,
            ).link_google_identity(
                admin_token=ADMIN_TOKEN,
                google_credential="invalid-credential",
            )

    assert await user_count(sessions) == 0


async def test_identity_linked_to_other_business_is_rejected(
    booking_client,
):
    _, sessions, _ = booking_client
    await enable_admin(sessions, business_id=1)
    await enable_admin(
        sessions,
        business_id=2,
        token="second-admin-token",
    )
    async with sessions.begin() as session:
        session.add(
            BusinessUser(
                business_id=2,
                email="owner@example.com",
                display_name="Owner",
                auth_provider="google",
                provider_subject="google-subject-1",
            )
        )

    async with sessions() as session:
        with pytest.raises(
            GoogleAdminAuthError,
            match="^Invalid Google admin authentication$",
        ):
            await GoogleAdminAuthService(
                session,
                verifier(),
            ).link_google_identity(
                admin_token=ADMIN_TOKEN,
                google_credential=GOOGLE_CREDENTIAL,
            )

    assert await user_count(sessions) == 1


async def test_linked_identity_can_authenticate(booking_client):
    _, sessions, _ = booking_client
    await enable_admin(sessions)
    async with sessions.begin() as session:
        session.add(
            BusinessUser(
                business_id=1,
                email="old-address@example.com",
                display_name="Old Name",
                auth_provider="google",
                provider_subject="google-subject-1",
            )
        )

    async with sessions() as session:
        result = await GoogleAdminAuthService(
            session,
            verifier(),
        ).authenticate_google(
            google_credential=GOOGLE_CREDENTIAL,
        )

    assert result.business.id == 1
    assert result.user.provider_subject == "google-subject-1"


async def test_unknown_valid_identity_does_not_auto_register(
    booking_client,
):
    _, sessions, _ = booking_client
    await enable_admin(sessions)

    async with sessions() as session:
        with pytest.raises(
            GoogleAdminAuthError,
            match="^Invalid Google admin authentication$",
        ):
            await GoogleAdminAuthService(
                session,
                verifier(),
            ).authenticate_google(
                google_credential=GOOGLE_CREDENTIAL,
            )

    assert await user_count(sessions) == 0


async def test_login_rejects_invalid_google_credential(
    booking_client,
):
    _, sessions, _ = booking_client
    google = verifier(error=GoogleIdentityError("token expired"))

    async with sessions() as session:
        with pytest.raises(
            GoogleAdminAuthError,
            match="^Invalid Google admin authentication$",
        ):
            await GoogleAdminAuthService(
                session,
                google,
            ).authenticate_google(
                google_credential="invalid-credential",
            )


async def test_login_requires_business_recovery_token(
    booking_client,
):
    _, sessions, _ = booking_client
    async with sessions.begin() as session:
        session.add(
            BusinessUser(
                business_id=1,
                email="owner@example.com",
                display_name="Owner",
                auth_provider="google",
                provider_subject="google-subject-1",
            )
        )

    async with sessions() as session:
        with pytest.raises(GoogleAdminAuthError):
            await GoogleAdminAuthService(
                session,
                verifier(),
            ).authenticate_google(
                google_credential=GOOGLE_CREDENTIAL,
            )


async def test_failed_relink_does_not_modify_existing_profile(
    booking_client,
):
    _, sessions, _ = booking_client
    await enable_admin(sessions, business_id=1)
    async with sessions.begin() as session:
        session.add(
            BusinessUser(
                business_id=2,
                email="original@example.com",
                display_name="Original",
                auth_provider="google",
                provider_subject="google-subject-1",
            )
        )

    async with sessions() as session:
        with pytest.raises(GoogleAdminAuthError):
            await GoogleAdminAuthService(
                session,
                verifier(
                    identity(
                        email="attacker@example.com",
                        display_name="Changed",
                    )
                ),
            ).link_google_identity(
                admin_token=ADMIN_TOKEN,
                google_credential=GOOGLE_CREDENTIAL,
            )

    async with sessions() as session:
        user = await session.scalar(select(BusinessUser))
        assert user.email == "original@example.com"
        assert user.display_name == "Original"
