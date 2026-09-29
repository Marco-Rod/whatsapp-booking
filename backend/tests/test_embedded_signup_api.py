import asyncio
from datetime import datetime, timedelta, timezone

from pydantic import SecretStr
import pytest
from sqlalchemy import func, select

from test_booking import booking_client  # noqa: F401

from app.api.v1 import embedded_signup
from app.core.config import settings
from app.core.database import get_session
from app.main import app
from app.models import Business, EmbeddedSignupAttempt, WhatsAppConnection
from app.security.admin_sessions import AdminSessionManager
from app.security.admin_tokens import hash_admin_token
from app.services.embedded_signup import (
    EmbeddedSignupAttemptConsumedError,
    EmbeddedSignupAttemptService,
    ValidatedEmbeddedSignupCompletion,
)


START_URL = "/api/v1/admin/whatsapp/embedded-signup/start"
COMPLETE_URL = "/api/v1/admin/whatsapp/embedded-signup/complete"
SESSION_SECRET = "embedded-signup-test-session-secret"


@pytest.fixture
def embedded_signup_config(monkeypatch):
    monkeypatch.setattr(settings, "admin_session_secret", SecretStr(SESSION_SECRET))
    monkeypatch.setattr(settings, "admin_session_max_age_seconds", 604800)
    config = settings.model_copy(
        update={
            "embedded_signup_attempt_ttl_seconds": 600,
            "embedded_signup_max_body_bytes": 16_384,
        }
    )
    app.dependency_overrides[
        embedded_signup.get_embedded_signup_settings
    ] = lambda: config
    yield config
    app.dependency_overrides.pop(
        embedded_signup.get_embedded_signup_settings,
        None,
    )


async def authenticate(client, sessions, business_id: int) -> None:
    admin_token = f"embedded-signup-admin-{business_id}"
    admin_hash = hash_admin_token(admin_token)
    async with sessions.begin() as session:
        business = await session.get(Business, business_id)
        business.admin_token_hash = admin_hash
    client.cookies.clear()
    client.cookies.set(
        "admin_session",
        AdminSessionManager(secret=SESSION_SECRET).create(
            business_id=business_id,
            admin_token_hash=admin_hash,
        ),
    )


def completion_payload(nonce: str, **overrides) -> dict:
    return {
        "attempt_nonce": nonce,
        "authorization_code": "test-authorization-code",
        "candidate_account_id": "123456789",
        "candidate_phone_number_id": "987654321",
        **overrides,
    }


async def start(client) -> dict:
    response = await client.post(START_URL)
    assert response.status_code == 200
    return response.json()


async def count_attempts(sessions) -> int:
    async with sessions() as session:
        return await session.scalar(
            select(func.count()).select_from(EmbeddedSignupAttempt)
        )


async def test_start_requires_admin_session(booking_client, embedded_signup_config):
    client, _, _ = booking_client

    assert (await client.post(START_URL)).status_code == 401


async def test_authenticated_start_creates_hashed_attempt_for_session_business(
    booking_client,
    embedded_signup_config,
):
    client, sessions, _ = booking_client
    await authenticate(client, sessions, 1)

    result = await start(client)

    assert set(result) == {"nonce", "expires_at"}
    assert len(result["nonce"]) >= 32
    async with sessions() as session:
        attempt = await session.scalar(select(EmbeddedSignupAttempt))
        assert attempt.business_id == 1
        assert attempt.nonce_hash != result["nonce"]
        assert result["nonce"] not in attempt.nonce_hash
        assert attempt.consumed_at is None


async def test_attempt_from_another_business_cannot_be_consumed(
    booking_client,
    embedded_signup_config,
):
    client, sessions, _ = booking_client
    await authenticate(client, sessions, 1)
    attempt = await start(client)

    await authenticate(client, sessions, 2)
    denied = await client.post(COMPLETE_URL, json=completion_payload(attempt["nonce"]))
    assert denied.status_code == 403

    await authenticate(client, sessions, 1)
    assert (await client.post(COMPLETE_URL, json=completion_payload(attempt["nonce"]))).status_code == 204


async def test_valid_completion_consumes_once_without_persisting_code(
    booking_client,
    embedded_signup_config,
):
    client, sessions, _ = booking_client
    await authenticate(client, sessions, 1)
    attempt = await start(client)
    body = completion_payload(attempt["nonce"])

    assert (await client.post(COMPLETE_URL, json=body)).status_code == 204
    assert (await client.post(COMPLETE_URL, json=body)).status_code == 409

    async with sessions() as session:
        stored = await session.scalar(select(EmbeddedSignupAttempt))
        assert stored.consumed_at is not None
        assert body["authorization_code"] not in repr(stored)
        assert body["authorization_code"] not in str(stored.__dict__)


async def test_completion_stops_at_the_a63_handoff_boundary(
    booking_client,
    embedded_signup_config,
):
    """A6.2 must not exchange Meta credentials or mutate connections."""
    client, sessions, _ = booking_client
    await authenticate(client, sessions, 1)
    attempt = await start(client)
    async with sessions() as session:
        connections_before = await session.scalar(
            select(func.count()).select_from(WhatsAppConnection)
        )

    response = await client.post(COMPLETE_URL, json=completion_payload(attempt["nonce"]))

    assert response.status_code == 204
    async with sessions() as session:
        connections_after = await session.scalar(
            select(func.count()).select_from(WhatsAppConnection)
        )
    assert connections_after == connections_before


async def test_expired_attempt_is_rejected_without_consumption(
    booking_client,
    embedded_signup_config,
):
    client, sessions, _ = booking_client
    await authenticate(client, sessions, 1)
    attempt = await start(client)
    async with sessions.begin() as session:
        stored = await session.scalar(select(EmbeddedSignupAttempt))
        stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    response = await client.post(COMPLETE_URL, json=completion_payload(attempt["nonce"]))
    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"attempt_nonce": "short"},
        {"attempt_nonce": "x" * 32, "authorization_code": ""},
        {"attempt_nonce": "x" * 32, "authorization_code": "code", "candidate_account_id": "abc", "candidate_phone_number_id": "2"},
        {"attempt_nonce": "x" * 32, "authorization_code": "code", "candidate_account_id": "1", "candidate_phone_number_id": "abc"},
        {"attempt_nonce": "x" * 32, "authorization_code": "code", "candidate_account_id": "1", "candidate_phone_number_id": "2", "business_id": 2},
    ],
)
async def test_completion_rejects_malformed_or_client_selected_tenant(
    booking_client,
    embedded_signup_config,
    payload,
):
    client, sessions, _ = booking_client
    await authenticate(client, sessions, 1)

    response = await client.post(COMPLETE_URL, json=payload)

    assert response.status_code == 422
    assert await count_attempts(sessions) == 0


async def test_completion_rejects_oversized_code_before_consuming_attempt(
    booking_client,
    embedded_signup_config,
):
    client, sessions, _ = booking_client
    await authenticate(client, sessions, 1)
    attempt = await start(client)

    response = await client.post(
        COMPLETE_URL,
        json=completion_payload(attempt["nonce"], authorization_code="x" * 4_097),
    )

    assert response.status_code == 422
    assert "x" * 4_097 not in response.text
    async with sessions() as session:
        stored = await session.scalar(select(EmbeddedSignupAttempt))
        assert stored.consumed_at is None


async def test_oversized_body_is_rejected_before_authentication_or_database(
    booking_client,
    embedded_signup_config,
):
    client, _, _ = booking_client
    config = embedded_signup_config.model_copy(
        update={"embedded_signup_max_body_bytes": 32}
    )
    app.dependency_overrides[
        embedded_signup.get_embedded_signup_settings
    ] = lambda: config
    session_calls = 0

    async def tracked_session():
        nonlocal session_calls
        session_calls += 1
        yield object()

    previous_session = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = tracked_session
    try:
        response = await client.post(
            COMPLETE_URL,
            content=b"x" * 33,
            headers={"Content-Type": "application/json"},
        )
    finally:
        if previous_session is None:
            app.dependency_overrides.pop(get_session, None)
        else:
            app.dependency_overrides[get_session] = previous_session

    assert response.status_code == 413
    assert session_calls == 0


async def test_concurrent_service_completion_has_exactly_one_success(
    booking_client,
    embedded_signup_config,
):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await EmbeddedSignupAttemptService(
            session,
            ttl_seconds=600,
        ).start(1)

    async def complete_once():
        async with sessions() as session:
            return await EmbeddedSignupAttemptService(
                session,
                ttl_seconds=600,
            ).complete(
                business_id=1,
                attempt_nonce=created.nonce,
                authorization_code="test-authorization-code",
                candidate_account_id="123456789",
                candidate_phone_number_id="987654321",
            )

    results = await asyncio.gather(
        complete_once(),
        complete_once(),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, EmbeddedSignupAttemptConsumedError) for result in results) == 1


def test_validated_completion_repr_hides_authorization_code():
    completion = ValidatedEmbeddedSignupCompletion(
        business_id=1,
        authorization_code="test-authorization-code",
        candidate_account_id="123456789",
        candidate_phone_number_id="987654321",
    )
    assert "test-authorization-code" not in repr(completion)
