from pydantic import SecretStr
import pytest
from pydantic import ValidationError

from test_booking import booking_client  # noqa: F401

from app.core.config import settings
from app.core.config import Settings
from app.models import Business
from app.security import admin_sessions
from app.security.admin_sessions import (
    AdminSessionError,
    AdminSessionManager,
    authenticate_admin_session,
)
from app.security.admin_tokens import hash_admin_token


SESSION_URL = "/api/v1/admin/session"
ONBOARDING_URL = "/api/v1/onboarding/status"
SESSION_SECRET = "test-independent-admin-session-secret"


def configure_sessions(*, secure=False):
    settings.admin_session_secret = SecretStr(SESSION_SECRET)
    settings.admin_session_max_age_seconds = 7 * 24 * 60 * 60
    settings.admin_session_cookie_secure = secure
    settings.admin_session_cookie_samesite = "lax"


async def enable_admin(sessions, business_id=1, token="admin-token"):
    async with sessions.begin() as session:
        business = await session.get(Business, business_id)
        business.admin_token_hash = hash_admin_token(token)
    return token


async def login(client, sessions, *, business_id=1, token="admin-token"):
    configure_sessions()
    await enable_admin(sessions, business_id, token)
    return await client.post(
        SESSION_URL,
        headers={"Authorization": f"Bearer {token}"},
    )


def test_admin_session_round_trip(monkeypatch):
    manager = AdminSessionManager(
        secret=SESSION_SECRET,
        max_age_seconds=60,
    )
    monkeypatch.setattr(admin_sessions.time, "time", lambda: 1_000)
    token = manager.create(
        business_id=42,
        admin_token_hash="a" * 64,
    )

    result = manager.verify(token)

    assert result.business_id == 42
    assert result.issued_at == 1_000
    assert result.expires_at == 1_060
    assert "a" * 64 not in token


def test_expired_admin_session_is_rejected(monkeypatch):
    manager = AdminSessionManager(
        secret=SESSION_SECRET,
        max_age_seconds=60,
    )
    monkeypatch.setattr(admin_sessions.time, "time", lambda: 1_000)
    token = manager.create(
        business_id=1,
        admin_token_hash="a" * 64,
    )
    monkeypatch.setattr(admin_sessions.time, "time", lambda: 1_060)

    with pytest.raises(AdminSessionError):
        manager.verify(token)


def test_tampered_admin_session_is_rejected():
    manager = AdminSessionManager(secret=SESSION_SECRET)
    token = manager.create(
        business_id=1,
        admin_token_hash="a" * 64,
    )
    replacement = "A" if token[-1] != "A" else "B"

    with pytest.raises(AdminSessionError):
        manager.verify(f"{token[:-1]}{replacement}")


async def test_login_sets_httponly_session_cookie(booking_client):
    client, sessions, _ = booking_client

    response = await login(client, sessions)

    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("admin_session=")
    assert "HttpOnly" in cookie
    assert "Max-Age=604800" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie


async def test_login_rejects_invalid_token_without_cookie(
    booking_client,
):
    client, sessions, _ = booking_client
    configure_sessions()
    await enable_admin(sessions)

    response = await client.post(
        SESSION_URL,
        headers={"Authorization": "Bearer wrong-token"},
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid business admin credentials"
    }
    assert "set-cookie" not in response.headers


async def test_valid_cookie_resolves_only_its_business(booking_client):
    client, sessions, _ = booking_client
    response = await login(
        client,
        sessions,
        business_id=2,
        token="second-admin-token",
    )
    assert response.status_code == 200

    status = await client.get(ONBOARDING_URL)

    assert status.status_code == 200
    assert status.json()["steps"]["business"] is True


async def test_tampered_cookie_has_generic_unauthorized_response(
    booking_client,
):
    client, sessions, _ = booking_client
    await login(client, sessions)
    cookie = client.cookies.get("admin_session")
    client.cookies.set("admin_session", f"{cookie}tampered")

    response = await client.get(ONBOARDING_URL)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid business admin credentials"
    }


async def test_expired_cookie_has_generic_unauthorized_response(
    booking_client,
    monkeypatch,
):
    client, sessions, _ = booking_client
    monkeypatch.setattr(admin_sessions.time, "time", lambda: 1_000)
    await login(client, sessions)
    monkeypatch.setattr(
        admin_sessions.time,
        "time",
        lambda: 1_000 + 7 * 24 * 60 * 60,
    )

    response = await client.get(ONBOARDING_URL)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid business admin credentials"
    }


async def test_rotating_admin_token_invalidates_existing_session(
    booking_client,
):
    client, sessions, _ = booking_client
    await login(client, sessions)

    async with sessions.begin() as session:
        business = await session.get(Business, 1)
        business.admin_token_hash = hash_admin_token("rotated-token")

    response = await client.get(ONBOARDING_URL)

    assert response.status_code == 401


async def test_session_cannot_be_used_for_another_business(
    booking_client,
):
    client, sessions, _ = booking_client
    configure_sessions()
    await enable_admin(sessions, 1, "first-token")
    await enable_admin(sessions, 2, "second-token")
    manager = AdminSessionManager(secret=SESSION_SECRET)

    async with sessions() as session:
        first = await session.get(Business, 1)
        token = manager.create(
            business_id=2,
            admin_token_hash=first.admin_token_hash,
        )
        with pytest.raises(AdminSessionError):
            await authenticate_admin_session(session, token, manager)


async def test_logout_expires_cookie_and_blocks_onboarding(
    booking_client,
):
    client, sessions, _ = booking_client
    await login(client, sessions)

    response = await client.delete(SESSION_URL)

    assert response.status_code == 200
    assert response.json() == {"authenticated": False}
    cookie = response.headers["set-cookie"]
    assert "admin_session=" in cookie
    assert "Max-Age=0" in cookie
    assert "HttpOnly" in cookie
    assert (await client.get(ONBOARDING_URL)).status_code == 401


async def test_secure_cookie_is_enabled_by_configuration(
    booking_client,
):
    client, sessions, _ = booking_client
    configure_sessions(secure=True)
    settings.admin_session_cookie_samesite = "none"
    token = await enable_admin(sessions)

    response = await client.post(
        SESSION_URL,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie
    assert "SameSite=none" in cookie


def test_samesite_none_requires_secure_cookie():
    with pytest.raises(
        ValidationError,
        match=(
            "ADMIN_SESSION_COOKIE_SAMESITE=none requires "
            "ADMIN_SESSION_COOKIE_SECURE=true"
        ),
    ):
        Settings(
            _env_file=None,
            admin_session_cookie_secure=False,
            admin_session_cookie_samesite="none",
        )


def test_local_cookie_policy_allows_lax_without_secure():
    config = Settings(
        _env_file=None,
        admin_session_cookie_secure=False,
        admin_session_cookie_samesite="lax",
    )

    assert config.admin_session_cookie_secure is False
    assert config.admin_session_cookie_samesite == "lax"


def test_credentialed_cors_rejects_wildcard_origin():
    with pytest.raises(
        ValidationError,
        match="must list explicit origins",
    ):
        Settings(
            _env_file=None,
            cors_allowed_origins=["*"],
        )


def test_current_production_cookie_and_origin_policy_is_valid():
    config = Settings(
        _env_file=None,
        admin_session_cookie_secure=True,
        admin_session_cookie_samesite="none",
        cors_allowed_origins=[
            "https://whatsapp-booking-blush.vercel.app"
        ],
    )

    assert config.admin_session_cookie_secure is True
    assert config.admin_session_cookie_samesite == "none"
    assert config.cors_allowed_origins == [
        "https://whatsapp-booking-blush.vercel.app"
    ]
