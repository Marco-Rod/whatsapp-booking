import asyncio
from datetime import datetime, timedelta, timezone

from pydantic import SecretStr
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as SyncSession

from test_booking import booking_client  # noqa: F401

from app.api.v1 import embedded_signup
from app.core.config import settings
from app.core.database import get_session
from app.main import app
from app.models import (
    Business,
    EmbeddedSignupAttempt,
    EmbeddedSignupAttemptStatus,
    WhatsAppConnection,
)
from app.security.admin_sessions import AdminSessionManager
from app.security.admin_tokens import hash_admin_token
from app.services.embedded_signup import (
    AcquiredEmbeddedSignupAttempt,
    EmbeddedSignupAttemptConsumedError,
    EmbeddedSignupAttemptExpiredError,
    EmbeddedSignupAttemptLeaseError,
    EmbeddedSignupAttemptOwnershipError,
    EmbeddedSignupAttemptProcessingError,
    EmbeddedSignupAttemptService,
    hash_processing_lease,
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
            "embedded_signup_processing_lease_seconds": 120,
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


def service(session, *, now=None) -> EmbeddedSignupAttemptService:
    return EmbeddedSignupAttemptService(
        session,
        ttl_seconds=600,
        processing_lease_seconds=120,
        now=now,
    )


async def start(client) -> dict:
    response = await client.post(START_URL)
    assert response.status_code == 200
    return response.json()


async def get_attempt(sessions) -> EmbeddedSignupAttempt:
    async with sessions() as session:
        return await session.scalar(select(EmbeddedSignupAttempt))


async def test_start_requires_admin_session(booking_client, embedded_signup_config):
    client, _, _ = booking_client
    assert (await client.post(START_URL)).status_code == 401


async def test_complete_requires_admin_session(booking_client, embedded_signup_config):
    client, _, _ = booking_client
    assert (
        await client.post(COMPLETE_URL, json=completion_payload("x" * 32))
    ).status_code == 401


async def test_authenticated_start_creates_hashed_ready_attempt(
    booking_client,
    embedded_signup_config,
):
    client, sessions, _ = booking_client
    await authenticate(client, sessions, 1)

    result = await start(client)
    attempt = await get_attempt(sessions)

    assert set(result) == {"nonce", "expires_at"}
    assert attempt.business_id == 1
    assert attempt.nonce_hash != result["nonce"]
    assert result["nonce"] not in attempt.nonce_hash
    assert attempt.status == EmbeddedSignupAttemptStatus.READY.value
    assert attempt.consumed_at is None
    assert attempt.processing_lease_hash is None


async def test_complete_is_explicitly_not_enabled_and_does_not_mutate_state(
    booking_client,
    embedded_signup_config,
):
    client, sessions, _ = booking_client
    await authenticate(client, sessions, 1)
    attempt = await start(client)
    async with sessions() as session:
        connections_before = await session.scalar(
            select(func.count()).select_from(WhatsAppConnection)
        )

    response = await client.post(COMPLETE_URL, json=completion_payload(attempt["nonce"]))

    assert response.status_code == 501
    stored = await get_attempt(sessions)
    assert stored.status == EmbeddedSignupAttemptStatus.READY.value
    assert "test-authorization-code" not in str(stored.__dict__)
    async with sessions() as session:
        connections_after = await session.scalar(
            select(func.count()).select_from(WhatsAppConnection)
        )
    assert connections_after == connections_before


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"attempt_nonce": "short"},
        {"attempt_nonce": "x" * 32, "authorization_code": ""},
        {
            "attempt_nonce": "x" * 32,
            "authorization_code": "code",
            "candidate_account_id": "invalid",
            "candidate_phone_number_id": "2",
        },
        {
            "attempt_nonce": "x" * 32,
            "authorization_code": "code",
            "candidate_account_id": "1",
            "candidate_phone_number_id": "2",
            "business_id": 2,
        },
    ],
)
async def test_complete_rejects_invalid_or_client_selected_tenant(
    booking_client,
    embedded_signup_config,
    payload,
):
    client, _, _ = booking_client
    await authenticate(client, booking_client[1], 1)
    assert (await client.post(COMPLETE_URL, json=payload)).status_code == 422


async def test_oversized_code_is_not_reflected_in_validation_error(
    booking_client,
    embedded_signup_config,
):
    client, sessions, _ = booking_client
    await authenticate(client, sessions, 1)
    attempt = await start(client)
    oversized_code = "x" * 4_097

    response = await client.post(
        COMPLETE_URL,
        json=completion_payload(attempt["nonce"], authorization_code=oversized_code),
    )

    assert response.status_code == 422
    assert oversized_code not in response.text


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


async def test_ready_attempt_acquires_hashed_lease(booking_client, embedded_signup_config):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await service(session).start(1)
    async with sessions() as session:
        acquired = await service(session).acquire(
            business_id=1,
            attempt_nonce=created.nonce,
        )

    stored = await get_attempt(sessions)
    assert stored.status == EmbeddedSignupAttemptStatus.PROCESSING.value
    assert stored.processing_lease_hash == hash_processing_lease(acquired.lease_token)
    assert acquired.lease_token not in repr(acquired)
    assert acquired.lease_token not in str(stored.__dict__)


async def test_concurrent_acquire_has_exactly_one_success(
    booking_client,
    embedded_signup_config,
):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await service(session).start(1)

    async def acquire_once():
        async with sessions() as session:
            return await service(session).acquire(
                business_id=1,
                attempt_nonce=created.nonce,
            )

    results = await asyncio.gather(
        acquire_once(),
        acquire_once(),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(
        isinstance(result, EmbeddedSignupAttemptProcessingError)
        for result in results
    ) == 1


async def test_active_lease_blocks_acquire(booking_client, embedded_signup_config):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await service(session).start(1)
    async with sessions() as session:
        await service(session).acquire(business_id=1, attempt_nonce=created.nonce)
    async with sessions() as session:
        with pytest.raises(EmbeddedSignupAttemptProcessingError):
            await service(session).acquire(business_id=1, attempt_nonce=created.nonce)


async def test_expired_lease_can_be_reacquired_with_new_capability(
    booking_client,
    embedded_signup_config,
):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await service(session).start(1)
    async with sessions() as session:
        first = await service(session).acquire(business_id=1, attempt_nonce=created.nonce)
    async with sessions.begin() as session:
        stored = await session.scalar(select(EmbeddedSignupAttempt))
        stored.processing_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with sessions() as session:
        second = await service(session).acquire(business_id=1, attempt_nonce=created.nonce)

    assert first.lease_token != second.lease_token


async def test_stale_lease_cannot_finalize_or_release(booking_client, embedded_signup_config):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await service(session).start(1)
    async with sessions() as session:
        stale = await service(session).acquire(business_id=1, attempt_nonce=created.nonce)
    async with sessions.begin() as session:
        stored = await session.scalar(select(EmbeddedSignupAttempt))
        stored.processing_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with sessions() as session:
        current = await service(session).acquire(business_id=1, attempt_nonce=created.nonce)
    async with sessions() as session:
        with pytest.raises(EmbeddedSignupAttemptLeaseError):
            await service(session).finalize_success(
                business_id=1,
                attempt_id=stale.attempt_id,
                lease_token=stale.lease_token,
            )
    async with sessions() as session:
        with pytest.raises(EmbeddedSignupAttemptLeaseError):
            await service(session).release(
                business_id=1,
                attempt_id=stale.attempt_id,
                lease_token=stale.lease_token,
            )
    assert current.lease_token != stale.lease_token


async def test_valid_finalize_consumes_and_blocks_reacquire(
    booking_client,
    embedded_signup_config,
):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await service(session).start(1)
    async with sessions() as session:
        acquired = await service(session).acquire(business_id=1, attempt_nonce=created.nonce)
    async with sessions() as session:
        await service(session).finalize_success(
            business_id=1,
            attempt_id=acquired.attempt_id,
            lease_token=acquired.lease_token,
        )

    stored = await get_attempt(sessions)
    assert stored.status == EmbeddedSignupAttemptStatus.CONSUMED.value
    assert stored.consumed_at is not None
    assert stored.processing_lease_hash is None
    async with sessions() as session:
        with pytest.raises(EmbeddedSignupAttemptConsumedError):
            await service(session).acquire(business_id=1, attempt_nonce=created.nonce)


async def test_finalize_wrong_tenant_or_expired_lease_fails(
    booking_client,
    embedded_signup_config,
):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await service(session).start(1)
    async with sessions() as session:
        acquired = await service(session).acquire(business_id=1, attempt_nonce=created.nonce)
    async with sessions() as session:
        with pytest.raises(EmbeddedSignupAttemptOwnershipError):
            await service(session).finalize_success(
                business_id=2,
                attempt_id=acquired.attempt_id,
                lease_token=acquired.lease_token,
            )
    async with sessions.begin() as session:
        stored = await session.scalar(select(EmbeddedSignupAttempt))
        stored.processing_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with sessions() as session:
        with pytest.raises(EmbeddedSignupAttemptLeaseError):
            await service(session).finalize_success(
                business_id=1,
                attempt_id=acquired.attempt_id,
                lease_token=acquired.lease_token,
            )


async def test_global_expiry_blocks_finalize_release_and_acquire(
    booking_client,
    embedded_signup_config,
):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await service(session).start(1)
    async with sessions() as session:
        acquired = await service(session).acquire(business_id=1, attempt_nonce=created.nonce)
    async with sessions.begin() as session:
        stored = await session.scalar(select(EmbeddedSignupAttempt))
        stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with sessions() as session:
        with pytest.raises(EmbeddedSignupAttemptExpiredError):
            await service(session).finalize_success(
                business_id=1,
                attempt_id=acquired.attempt_id,
                lease_token=acquired.lease_token,
            )
    async with sessions() as session:
        with pytest.raises(EmbeddedSignupAttemptExpiredError):
            await service(session).release(
                business_id=1,
                attempt_id=acquired.attempt_id,
                lease_token=acquired.lease_token,
            )
    async with sessions() as session:
        with pytest.raises(EmbeddedSignupAttemptExpiredError):
            await service(session).acquire(business_id=1, attempt_nonce=created.nonce)


async def test_valid_release_returns_attempt_to_ready(booking_client, embedded_signup_config):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await service(session).start(1)
    async with sessions() as session:
        acquired = await service(session).acquire(business_id=1, attempt_nonce=created.nonce)
    async with sessions() as session:
        await service(session).release(
            business_id=1,
            attempt_id=acquired.attempt_id,
            lease_token=acquired.lease_token,
        )

    stored = await get_attempt(sessions)
    assert stored.status == EmbeddedSignupAttemptStatus.READY.value
    assert stored.processing_started_at is None
    assert stored.processing_expires_at is None
    assert stored.processing_lease_hash is None


async def test_finalize_rollback_keeps_processing_state(booking_client, embedded_signup_config):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await service(session).start(1)
    async with sessions() as session:
        acquired = await service(session).acquire(business_id=1, attempt_nonce=created.nonce)
    async with sessions() as session:
        with pytest.raises(RuntimeError):
            async with session.begin():
                await service(session).finalize_success_in_transaction(
                    business_id=1,
                    attempt_id=acquired.attempt_id,
                    lease_token=acquired.lease_token,
                )
                raise RuntimeError("rollback")

    stored = await get_attempt(sessions)
    assert stored.status == EmbeddedSignupAttemptStatus.PROCESSING.value
    assert stored.consumed_at is None


async def test_acquire_rollback_keeps_attempt_ready_and_reacquirable(
    booking_client,
    embedded_signup_config,
):
    _, sessions, _ = booking_client
    async with sessions() as session:
        created = await service(session).start(1)

    def fail_commit(_session):
        raise SQLAlchemyError("simulated acquire commit rejection")

    event.listen(SyncSession, "before_commit", fail_commit)
    try:
        async with sessions() as session:
            with pytest.raises(SQLAlchemyError, match="acquire commit rejection"):
                await service(session).acquire(
                    business_id=1,
                    attempt_nonce=created.nonce,
                )
    finally:
        event.remove(SyncSession, "before_commit", fail_commit)

    stored = await get_attempt(sessions)
    assert stored.status == EmbeddedSignupAttemptStatus.READY.value
    assert stored.consumed_at is None
    assert stored.processing_started_at is None
    assert stored.processing_expires_at is None
    assert stored.processing_lease_hash is None

    async with sessions() as session:
        reacquired = await service(session).acquire(
            business_id=1,
            attempt_nonce=created.nonce,
        )
    assert reacquired.attempt_id == stored.id


def test_lease_capability_repr_is_safe():
    acquired = AcquiredEmbeddedSignupAttempt(
        attempt_id=1,
        business_id=1,
        expires_at=datetime.now(timezone.utc),
        processing_expires_at=datetime.now(timezone.utc),
        lease_token="test-lease-token",
    )
    assert "test-lease-token" not in repr(acquired)


def test_authorization_code_is_not_in_request_repr():
    from app.schemas.embedded_signup import EmbeddedSignupCompleteRequest

    request = EmbeddedSignupCompleteRequest(**completion_payload("x" * 32))
    assert "test-authorization-code" not in repr(request)
