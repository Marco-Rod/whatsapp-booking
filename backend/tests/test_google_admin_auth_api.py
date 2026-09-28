from unittest.mock import AsyncMock

from pydantic import SecretStr
import pytest
from sqlalchemy import func, select

from test_booking import booking_client  # noqa: F401

from app.api.v1 import google_admin_auth
from app.core.config import Settings, settings
from app.core.database import get_session
from app.main import app
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
AUTH_BODY_LIMIT = 32


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


def install_body_limit(monkeypatch):
    config = settings.model_copy(
        update={"google_admin_auth_max_body_bytes": AUTH_BODY_LIMIT},
    )
    app.dependency_overrides[
        google_admin_auth.get_google_admin_auth_settings
    ] = lambda: config

    session_calls = 0

    async def tracked_session():
        nonlocal session_calls
        session_calls += 1
        yield object()

    previous_session_override = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = tracked_session

    def cleanup():
        app.dependency_overrides.pop(
            google_admin_auth.get_google_admin_auth_settings,
            None,
        )
        if previous_session_override is None:
            app.dependency_overrides.pop(get_session, None)
        else:
            app.dependency_overrides[get_session] = previous_session_override

    return lambda: session_calls, cleanup


async def post_without_content_length(path, chunks, headers=None, *, disconnect=False):
    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": disconnect or index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    sent = []

    async def receive():
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers or [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        },
        receive,
        send,
    )
    return next(
        message["status"]
        for message in sent
        if message["type"] == "http.response.start"
    )


def test_google_admin_auth_body_limit_must_be_positive():
    with pytest.raises(ValueError):
        Settings(_env_file=None, google_admin_auth_max_body_bytes=0)


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


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        (SESSION_URL, {}),
        (LINK_URL, {"Authorization": "Bearer bootstrap-token"}),
    ],
)
async def test_google_auth_content_length_over_limit_rejects_before_verifier_or_session(
    booking_client,
    monkeypatch,
    path,
    headers,
):
    client, _, _ = booking_client
    session_calls, cleanup = install_body_limit(monkeypatch)
    verifier = use_google_verifier(monkeypatch)
    try:
        response = await client.post(
            path,
            content=b"x" * (AUTH_BODY_LIMIT + 1),
            headers=headers,
        )
        assert response.status_code == 413
        verifier.verify.assert_not_awaited()
        assert session_calls() == 0
    finally:
        cleanup()


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        (SESSION_URL, []),
        (LINK_URL, [(b"authorization", b"Bearer bootstrap-token")]),
    ],
)
async def test_google_auth_chunked_body_over_limit_rejects_before_verifier_or_session(
    booking_client,
    monkeypatch,
    path,
    headers,
):
    _, _, _ = booking_client
    session_calls, cleanup = install_body_limit(monkeypatch)
    verifier = use_google_verifier(monkeypatch)
    try:
        status = await post_without_content_length(
            path,
            [b"x" * AUTH_BODY_LIMIT, b"x"],
            headers=headers,
        )
        assert status == 413
        verifier.verify.assert_not_awaited()
        assert session_calls() == 0
    finally:
        cleanup()


async def test_google_auth_invalid_body_preserves_422_before_verifier_or_session(
    booking_client,
    monkeypatch,
):
    client, _, _ = booking_client
    session_calls, cleanup = install_body_limit(monkeypatch)
    verifier = use_google_verifier(monkeypatch)
    try:
        response = await client.post(SESSION_URL, json={})
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["body", "credential"]
        verifier.verify.assert_not_awaited()
        assert session_calls() == 0
    finally:
        cleanup()


async def test_google_auth_body_at_limit_reaches_validation_before_session(
    booking_client,
    monkeypatch,
):
    client, _, _ = booking_client
    session_calls, cleanup = install_body_limit(monkeypatch)
    verifier = use_google_verifier(monkeypatch)
    try:
        response = await client.post(SESSION_URL, content=b"x" * AUTH_BODY_LIMIT)
        assert response.status_code == 422
        verifier.verify.assert_not_awaited()
        assert session_calls() == 0
    finally:
        cleanup()


async def test_google_auth_interrupted_body_rejects_before_verifier_or_session(
    booking_client,
    monkeypatch,
):
    _, _, _ = booking_client
    session_calls, cleanup = install_body_limit(monkeypatch)
    verifier = use_google_verifier(monkeypatch)
    try:
        status = await post_without_content_length(
            SESSION_URL,
            [b'{"credential":"partial'],
            disconnect=True,
        )
        assert status == 400
        verifier.verify.assert_not_awaited()
        assert session_calls() == 0
    finally:
        cleanup()


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
