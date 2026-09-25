from unittest.mock import AsyncMock

from pydantic import SecretStr
import pytest
from sqlalchemy import func, select

from test_booking import booking_client  # noqa: F401

from app.api.v1 import google_admin_auth
from app.core.config import settings
from app.models import Business, BusinessUser
from app.security.admin_sessions import AdminSessionManager
from app.security.admin_tokens import hash_admin_token
from app.security.google_identity import (
    GoogleIdentity,
    GoogleIdentityError,
)


LINK_URL = "/api/v1/admin/google/link"
SESSION_URL = "/api/v1/admin/google/session"
ONBOARDING_URL = "/api/v1/onboarding/status"
ADMIN_TOKEN = "bella-admin-token"
GOOGLE_CREDENTIAL = "google-id-token-value"
SESSION_SECRET = "google-admin-api-session-secret"


def configure_session_cookie(*, secure=False, samesite="lax"):
    settings.admin_session_secret = SecretStr(SESSION_SECRET)
    settings.admin_session_max_age_seconds = 7 * 24 * 60 * 60
    settings.admin_session_cookie_secure = secure
    settings.admin_session_cookie_samesite = samesite


def trusted_identity(subject="google-subject-1"):
    return GoogleIdentity(
        subject=subject,
        email="owner@example.com",
        display_name="Owner",
        email_verified=True,
    )


def use_google_verifier(monkeypatch, *, result=None, error=None):
    verifier = AsyncMock()
    if error is not None:
        verifier.verify.side_effect = error
    else:
        verifier.verify.return_value = result or trusted_identity()
    monkeypatch.setattr(
        google_admin_auth,
        "build_google_identity_verifier",
        lambda: verifier,
    )
    return verifier


async def enable_admin(sessions, business_id=1, token=ADMIN_TOKEN):
    async with sessions.begin() as session:
        business = await session.get(Business, business_id)
        business.admin_token_hash = hash_admin_token(token)


async def add_linked_user(sessions, business_id=1):
    async with sessions.begin() as session:
        session.add(
            BusinessUser(
                business_id=business_id,
                email="owner@example.com",
                display_name="Owner",
                auth_provider="google",
                provider_subject="google-subject-1",
            )
        )


async def test_google_link_creates_user_and_session_cookie(
    booking_client,
    monkeypatch,
):
    client, sessions, _ = booking_client
    configure_session_cookie()
    await enable_admin(sessions)
    use_google_verifier(monkeypatch)

    response = await client.post(
        LINK_URL,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json={"credential": GOOGLE_CREDENTIAL},
    )

    assert response.status_code == 204
    assert response.content == b""
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("admin_session=")
    assert "HttpOnly" in cookie
    assert GOOGLE_CREDENTIAL not in cookie
    async with sessions() as session:
        user = await session.scalar(select(BusinessUser))
        assert user.business_id == 1
        assert user.provider_subject == "google-subject-1"


async def test_repeated_google_link_remains_idempotent(
    booking_client,
    monkeypatch,
):
    client, sessions, _ = booking_client
    configure_session_cookie()
    await enable_admin(sessions)
    use_google_verifier(monkeypatch)

    first = await client.post(
        LINK_URL,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json={"credential": GOOGLE_CREDENTIAL},
    )
    second = await client.post(
        LINK_URL,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json={"credential": GOOGLE_CREDENTIAL},
    )

    assert first.status_code == second.status_code == 204
    async with sessions() as session:
        count = await session.scalar(
            select(func.count()).select_from(BusinessUser)
        )
        assert count == 1


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic credentials"},
        {"Authorization": "Bearer wrong-token"},
    ],
    ids=["missing", "malformed", "incorrect"],
)
async def test_google_link_rejects_invalid_admin_authorization(
    booking_client,
    monkeypatch,
    headers,
):
    client, sessions, _ = booking_client
    configure_session_cookie()
    await enable_admin(sessions)
    use_google_verifier(monkeypatch)

    response = await client.post(
        LINK_URL,
        headers=headers,
        json={"credential": GOOGLE_CREDENTIAL},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid Google admin authentication"
    }
    assert "set-cookie" not in response.headers


async def test_google_link_rejects_invalid_google_credential(
    booking_client,
    monkeypatch,
):
    client, sessions, _ = booking_client
    configure_session_cookie()
    await enable_admin(sessions)
    use_google_verifier(
        monkeypatch,
        error=GoogleIdentityError("signature detail"),
    )

    response = await client.post(
        LINK_URL,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json={"credential": GOOGLE_CREDENTIAL},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid Google admin authentication"
    }
    assert "set-cookie" not in response.headers
    assert GOOGLE_CREDENTIAL not in response.text


async def test_linked_google_identity_creates_session(
    booking_client,
    monkeypatch,
):
    client, sessions, _ = booking_client
    configure_session_cookie()
    await enable_admin(sessions)
    await add_linked_user(sessions)
    use_google_verifier(monkeypatch)

    response = await client.post(
        SESSION_URL,
        json={"credential": GOOGLE_CREDENTIAL},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["set-cookie"].startswith(
        "admin_session="
    )


async def test_unknown_google_identity_cannot_login(
    booking_client,
    monkeypatch,
):
    client, sessions, _ = booking_client
    configure_session_cookie()
    await enable_admin(sessions)
    use_google_verifier(monkeypatch)

    response = await client.post(
        SESSION_URL,
        json={"credential": GOOGLE_CREDENTIAL},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid Google admin authentication"
    }
    assert "set-cookie" not in response.headers


async def test_google_session_cookie_authorizes_onboarding(
    booking_client,
    monkeypatch,
):
    client, sessions, _ = booking_client
    configure_session_cookie()
    await enable_admin(sessions)
    await add_linked_user(sessions)
    use_google_verifier(monkeypatch)
    assert (
        await client.post(
            SESSION_URL,
            json={"credential": GOOGLE_CREDENTIAL},
        )
    ).status_code == 204

    response = await client.get(ONBOARDING_URL)

    assert response.status_code == 200


async def test_google_session_can_be_logged_out(
    booking_client,
    monkeypatch,
):
    client, sessions, _ = booking_client
    configure_session_cookie()
    await enable_admin(sessions)
    await add_linked_user(sessions)
    use_google_verifier(monkeypatch)
    await client.post(
        SESSION_URL,
        json={"credential": GOOGLE_CREDENTIAL},
    )

    logout = await client.delete("/api/v1/admin/session")

    assert logout.status_code == 200
    assert (await client.get(ONBOARDING_URL)).status_code == 401


async def test_admin_token_rotation_invalidates_google_session(
    booking_client,
    monkeypatch,
):
    client, sessions, _ = booking_client
    configure_session_cookie()
    await enable_admin(sessions)
    await add_linked_user(sessions)
    use_google_verifier(monkeypatch)
    await client.post(
        SESSION_URL,
        json={"credential": GOOGLE_CREDENTIAL},
    )

    async with sessions.begin() as session:
        business = await session.get(Business, 1)
        business.admin_token_hash = hash_admin_token("rotated")

    assert (await client.get(ONBOARDING_URL)).status_code == 401


@pytest.mark.parametrize(
    ("secure", "samesite", "expected"),
    [
        (False, "lax", ["HttpOnly", "SameSite=lax"]),
        (True, "none", ["HttpOnly", "Secure", "SameSite=none"]),
    ],
    ids=["local", "production"],
)
async def test_google_session_uses_central_cookie_configuration(
    booking_client,
    monkeypatch,
    secure,
    samesite,
    expected,
):
    client, sessions, _ = booking_client
    configure_session_cookie(secure=secure, samesite=samesite)
    await enable_admin(sessions)
    await add_linked_user(sessions)
    use_google_verifier(monkeypatch)

    response = await client.post(
        SESSION_URL,
        json={"credential": GOOGLE_CREDENTIAL},
    )

    cookie = response.headers["set-cookie"]
    assert all(attribute in cookie for attribute in expected)


async def test_google_login_ignores_authorization_header(
    booking_client,
    monkeypatch,
):
    client, sessions, _ = booking_client
    configure_session_cookie()
    await enable_admin(sessions, business_id=1)
    await enable_admin(
        sessions,
        business_id=2,
        token="second-business-token",
    )
    await add_linked_user(sessions, business_id=1)
    use_google_verifier(monkeypatch)

    response = await client.post(
        SESSION_URL,
        headers={"Authorization": "Bearer second-business-token"},
        json={"credential": GOOGLE_CREDENTIAL},
    )

    assert response.status_code == 204
    cookie = response.cookies.get("admin_session")
    signed = AdminSessionManager(
        secret=SESSION_SECRET,
    ).verify(cookie)
    assert signed.business_id == 1
