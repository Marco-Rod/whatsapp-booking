import pytest

from test_booking import booking_client  # noqa: F401

from app.models import Business
from app.security import admin_tokens
from app.security.admin_tokens import (
    BusinessAdminAuthenticationError,
    authenticate_business_admin,
    generate_admin_token,
    hash_admin_token,
)


async def enable_admin_access(sessions, business_id=1):
    token = generate_admin_token()
    async with sessions.begin() as session:
        business = await session.get(Business, business_id)
        business.admin_token_hash = hash_admin_token(token)
    return token


def test_generate_admin_token_has_sufficient_entropy():
    first = generate_admin_token()
    second = generate_admin_token()

    assert first != second
    assert len(first) >= 43


def test_hash_admin_token_is_deterministic_and_one_way():
    token = "plain-admin-token"
    digest = hash_admin_token(token)

    assert digest == hash_admin_token(token)
    assert digest != token
    assert len(digest) == 64
    assert token not in digest


@pytest.mark.parametrize("token", ["", None])
def test_empty_admin_token_is_rejected(token):
    with pytest.raises(
        BusinessAdminAuthenticationError,
        match="Invalid business admin credentials",
    ):
        hash_admin_token(token)


async def test_correct_token_authenticates_business(
    booking_client,
):
    _, sessions, _ = booking_client
    token = await enable_admin_access(sessions)

    async with sessions() as session:
        business = await authenticate_business_admin(
            session,
            token,
        )

    assert business.id == 1


async def test_incorrect_token_is_rejected(booking_client):
    _, sessions, _ = booking_client
    await enable_admin_access(sessions)

    async with sessions() as session:
        with pytest.raises(
            BusinessAdminAuthenticationError,
            match="Invalid business admin credentials",
        ):
            await authenticate_business_admin(
                session,
                "incorrect-token",
            )


async def test_business_without_token_is_rejected(booking_client):
    _, sessions, _ = booking_client

    async with sessions() as session:
        with pytest.raises(BusinessAdminAuthenticationError):
            await authenticate_business_admin(
                session,
                "unconfigured-business-token",
            )


async def test_authentication_uses_constant_time_comparison(
    booking_client,
    monkeypatch,
):
    _, sessions, _ = booking_client
    token = await enable_admin_access(sessions)
    calls = []
    original = admin_tokens.hmac.compare_digest

    def compare_digest(first, second):
        calls.append((first, second))
        return original(first, second)

    monkeypatch.setattr(
        admin_tokens.hmac,
        "compare_digest",
        compare_digest,
    )

    async with sessions() as session:
        await authenticate_business_admin(session, token)

    assert calls == [
        (hash_admin_token(token), hash_admin_token(token))
    ]


async def test_only_token_hash_is_persisted(booking_client):
    _, sessions, _ = booking_client
    token = await enable_admin_access(sessions)

    async with sessions() as session:
        business = await session.get(Business, 1)
        stored = business.admin_token_hash

    assert stored == hash_admin_token(token)
    assert stored != token
    assert token not in stored
