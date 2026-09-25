from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from test_booking import booking_client  # noqa: F401

from app.api.v1 import google_integrations
from app.core.config import Settings
from app.integrations.google_calendar.oauth import GoogleOAuthExchangeError
from app.models import Appointment, GoogleCalendarConnection
from app.security.credentials import CredentialCipher
from app.security.oauth_state import OAuthStateError


async def test_google_disconnect_cors_preflight_allows_delete(
    booking_client,
):
    client, _, _ = booking_client

    response = await client.options(
        "/api/v1/businesses/1/integrations/google",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:5173"
    )
    assert "DELETE" in response.headers["access-control-allow-methods"]


STATUS_URL = "/api/v1/businesses/1/integrations/google"


@pytest.fixture
def oauth_dependencies(monkeypatch):
    state_manager = Mock()
    state_manager.create.return_value = "signed-test-state"

    oauth = Mock()
    oauth.generate_code_verifier.return_value = (
        "test-code-verifier"
    )
    oauth.build_authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth"
        "?client_id=test-client"
        "&state=signed-test-state"
    )

    monkeypatch.setattr(
        google_integrations,
        "build_oauth_state_manager",
        lambda: state_manager,
    )
    monkeypatch.setattr(
        google_integrations,
        "build_google_oauth_service",
        lambda: oauth,
    )

    return state_manager, oauth


@pytest.fixture
def callback_dependencies(monkeypatch):
    state_manager = Mock()
    state_manager.verify.return_value = SimpleNamespace(
        business_id=1,
        code_verifier="test-code-verifier",
    )

    oauth = Mock()
    oauth.exchange_code.return_value = SimpleNamespace(
        refresh_token="google-refresh-token-secret",
        scopes=[
            "https://www.googleapis.com/auth/calendar.events"
        ],
    )

    cipher = Mock()
    cipher.encrypt.return_value = "encrypted-refresh-token"

    monkeypatch.setattr(
        google_integrations,
        "build_oauth_state_manager",
        lambda: state_manager,
    )
    monkeypatch.setattr(
        google_integrations,
        "build_google_oauth_service",
        lambda: oauth,
    )
    monkeypatch.setattr(
        google_integrations,
        "build_credential_cipher",
        lambda: cipher,
    )
    monkeypatch.setattr(
        google_integrations.settings,
        "frontend_url",
        "http://frontend.test",
    )

    return state_manager, oauth, cipher


def test_frontend_url_configuration(monkeypatch):
    monkeypatch.setenv(
        "FRONTEND_URL",
        "https://dashboard.example",
    )

    config = Settings(_env_file=None)

    assert config.frontend_url == "https://dashboard.example"


async def add_google_connection(sessions):
    async with sessions.begin() as session:
        session.add(
            GoogleCalendarConnection(
                business_id=1,
                calendar_id="primary",
                encrypted_refresh_token="encrypted-refresh-token",
                scopes=[
                    "https://www.googleapis.com/auth/calendar.events"
                ],
            )
        )


async def test_google_status_returns_404_for_unknown_business(booking_client):
    client, _, _ = booking_client

    response = await client.get(
        "/api/v1/businesses/999/integrations/google"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Business not found",
    }


async def test_google_status_returns_disconnected(booking_client):
    client, _, _ = booking_client

    response = await client.get(STATUS_URL)

    assert response.status_code == 200
    assert response.json() == {
        "connected": False,
        "calendar_id": None,
        "connected_at": None,
    }


async def test_google_status_returns_connected(booking_client):
    client, sessions, _ = booking_client
    await add_google_connection(sessions)

    response = await client.get(STATUS_URL)
    data = response.json()

    assert response.status_code == 200
    assert data["connected"] is True
    assert data["calendar_id"] == "primary"
    assert data["connected_at"] is not None


async def test_google_status_does_not_expose_credentials(booking_client):
    client, sessions, _ = booking_client
    await add_google_connection(sessions)

    response = await client.get(STATUS_URL)
    data = response.json()

    assert response.status_code == 200
    assert set(data) == {
        "connected",
        "calendar_id",
        "connected_at",
    }
    assert "encrypted_refresh_token" not in response.text
    assert "encrypted-refresh-token" not in response.text
    assert "scopes" not in data


async def test_google_disconnect_returns_404_for_unknown_business(
    booking_client,
):
    client, _, _ = booking_client

    response = await client.delete(
        "/api/v1/businesses/999/integrations/google"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Business not found",
    }


async def test_google_disconnect_deletes_existing_connection(booking_client):
    client, sessions, _ = booking_client
    await add_google_connection(sessions)

    response = await client.delete(STATUS_URL)

    assert response.status_code == 200
    assert response.json() == {
        "connected": False,
    }
    async with sessions() as session:
        connection = await session.scalar(
            select(GoogleCalendarConnection)
        )
        assert connection is None


async def test_google_disconnect_is_idempotent(booking_client):
    client, sessions, _ = booking_client
    await add_google_connection(sessions)

    first = await client.delete(STATUS_URL)
    second = await client.delete(STATUS_URL)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == {
        "connected": False,
    }


async def test_google_disconnect_preserves_appointment_calendar_event_id(
    booking_client,
):
    client, sessions, _ = booking_client
    await add_google_connection(sessions)
    start = datetime.now(timezone.utc) + timedelta(days=1)
    async with sessions.begin() as session:
        appointment = Appointment(
            business_id=1,
            service_id=1,
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            status="CONFIRMED",
            calendar_event_id="historical-google-event",
        )
        session.add(appointment)
        await session.flush()
        appointment_id = appointment.id

    response = await client.delete(STATUS_URL)

    assert response.status_code == 200
    async with sessions() as session:
        appointment = await session.get(Appointment, appointment_id)
        assert (
            appointment.calendar_event_id
            == "historical-google-event"
        )


async def test_google_disconnect_status_and_no_provider_calls(
    booking_client,
    monkeypatch,
):
    client, sessions, _ = booking_client
    await add_google_connection(sessions)
    oauth_factory = Mock()
    cipher_factory = Mock()
    state_factory = Mock()
    monkeypatch.setattr(
        google_integrations,
        "build_google_oauth_service",
        oauth_factory,
    )
    monkeypatch.setattr(
        google_integrations,
        "build_credential_cipher",
        cipher_factory,
    )
    monkeypatch.setattr(
        google_integrations,
        "build_oauth_state_manager",
        state_factory,
    )

    disconnected = await client.delete(STATUS_URL)
    status = await client.get(STATUS_URL)

    assert disconnected.status_code == 200
    assert status.status_code == 200
    assert status.json() == {
        "connected": False,
        "calendar_id": None,
        "connected_at": None,
    }
    oauth_factory.assert_not_called()
    cipher_factory.assert_not_called()
    state_factory.assert_not_called()


async def test_google_connect_redirects_to_google(
    booking_client,
    oauth_dependencies,
):
    client, _, _ = booking_client
    state_manager, oauth = oauth_dependencies

    response = await client.get(
        "/api/v1/businesses/1/integrations/google/connect",
        follow_redirects=False,
    )

    assert response.status_code == 302

    assert response.headers["location"].startswith(
        "https://accounts.google.com/o/oauth2/auth"
    )

    state_manager.create.assert_called_once_with(
        business_id=1,
        code_verifier="test-code-verifier",
    )

    oauth.build_authorization_url.assert_called_once_with(
        state="signed-test-state",
        code_verifier="test-code-verifier",
    )


async def test_google_connect_returns_404_for_unknown_business(
    booking_client,
    oauth_dependencies,
):
    client, _, _ = booking_client
    state_manager, oauth = oauth_dependencies

    response = await client.get(
        "/api/v1/businesses/999/integrations/google/connect",
        follow_redirects=False,
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Business not found",
    }

    state_manager.create.assert_not_called()
    oauth.build_authorization_url.assert_not_called()


async def test_google_callback_creates_encrypted_connection(
    booking_client,
    callback_dependencies,
):
    client, sessions, _ = booking_client
    state_manager, oauth, cipher = callback_dependencies

    response = await client.get(
        "/api/v1/integrations/google/callback",
        params={
            "code": "google-auth-code",
            "state": "signed-state",
        },
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "http://frontend.test/?google_calendar=connected"
    )

    state_manager.verify.assert_called_once_with(
        "signed-state"
    )
    oauth.exchange_code.assert_called_once_with(
        code="google-auth-code",
        code_verifier="test-code-verifier",
    )
    cipher.encrypt.assert_called_once_with(
        "google-refresh-token-secret"
    )

    async with sessions() as session:
        connection = await session.scalar(
            select(GoogleCalendarConnection).where(
                GoogleCalendarConnection.business_id == 1
            )
        )

        assert connection is not None
        assert connection.business_id == 1
        assert connection.calendar_id == "primary"
        assert (
            connection.encrypted_refresh_token
            == "encrypted-refresh-token"
        )
        assert (
            connection.encrypted_refresh_token
            != "google-refresh-token-secret"
        )
        assert connection.scopes == [
            "https://www.googleapis.com/auth/calendar.events"
        ]


async def test_google_callback_updates_existing_connection(
    booking_client,
    callback_dependencies,
):
    client, sessions, _ = booking_client
    _, oauth, cipher = callback_dependencies

    first = await client.get(
        "/api/v1/integrations/google/callback",
        params={
            "code": "first-code",
            "state": "first-state",
        },
    )

    assert first.status_code == 303

    oauth.exchange_code.return_value = SimpleNamespace(
        refresh_token="new-refresh-token",
        scopes=[
            "https://www.googleapis.com/auth/calendar.events"
        ],
    )
    cipher.encrypt.return_value = "new-encrypted-token"

    second = await client.get(
        "/api/v1/integrations/google/callback",
        params={
            "code": "second-code",
            "state": "second-state",
        },
    )

    assert second.status_code == 303

    async with sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(GoogleCalendarConnection)
        )

        connection = await session.scalar(
            select(GoogleCalendarConnection).where(
                GoogleCalendarConnection.business_id == 1
            )
        )

        assert count == 1
        assert (
            connection.encrypted_refresh_token
            == "new-encrypted-token"
        )


async def test_google_callback_returns_404_for_unknown_business(
    booking_client,
    callback_dependencies,
):
    client, _, _ = booking_client
    state_manager, oauth, cipher = callback_dependencies

    state_manager.verify.return_value = SimpleNamespace(
        business_id=999,
        code_verifier="test-code-verifier",
    )

    response = await client.get(
        "/api/v1/integrations/google/callback",
        params={
            "code": "google-auth-code",
            "state": "signed-state",
        },
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Business not found",
    }

    oauth.exchange_code.assert_not_called()
    cipher.encrypt.assert_not_called()


async def test_google_callback_rejects_invalid_state(
    booking_client,
    callback_dependencies,
):
    client, _, _ = booking_client
    state_manager, oauth, cipher = callback_dependencies

    state_manager.verify.side_effect = OAuthStateError(
        "OAuth state has expired"
    )

    response = await client.get(
        "/api/v1/integrations/google/callback",
        params={
            "code": "google-auth-code",
            "state": "invalid-state",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Invalid or expired OAuth state"
    }

    oauth.exchange_code.assert_not_called()
    cipher.encrypt.assert_not_called()


async def test_google_callback_rejects_exchange_failure(
    booking_client,
    callback_dependencies,
):
    client, sessions, _ = booking_client
    _, oauth, cipher = callback_dependencies

    oauth.exchange_code.side_effect = GoogleOAuthExchangeError(
        "Google rejected authorization code"
    )

    response = await client.get(
        "/api/v1/integrations/google/callback",
        params={
            "code": "invalid-code",
            "state": "signed-state",
        },
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "http://frontend.test/?google_calendar=error"
    )
    assert "invalid-code" not in response.headers["location"]
    assert "signed-state" not in response.headers["location"]
    assert "Google rejected" not in response.headers["location"]

    cipher.encrypt.assert_not_called()

    async with sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(GoogleCalendarConnection)
        )

        assert count == 0


async def test_google_reconnect_without_refresh_token_preserves_ciphertext(
    booking_client,
    callback_dependencies,
):
    client, sessions, _ = booking_client
    _, oauth, cipher = callback_dependencies
    await add_google_connection(sessions)
    oauth.exchange_code.return_value = SimpleNamespace(
        refresh_token=None,
        scopes=[
            "https://www.googleapis.com/auth/calendar.events"
        ],
    )

    response = await client.get(
        "/api/v1/integrations/google/callback",
        params={
            "code": "reconnect-code",
            "state": "signed-state",
        },
    )

    assert response.status_code == 303
    cipher.encrypt.assert_not_called()
    async with sessions() as session:
        connection = await session.scalar(
            select(GoogleCalendarConnection)
        )
        assert (
            connection.encrypted_refresh_token
            == "encrypted-refresh-token"
        )


async def test_google_reconnect_replaces_refresh_token(
    booking_client,
    callback_dependencies,
    monkeypatch,
):
    client, sessions, _ = booking_client
    _, oauth, _ = callback_dependencies
    cipher = CredentialCipher(
        Fernet.generate_key().decode("utf-8")
    )
    old_ciphertext = cipher.encrypt("old-refresh-token")
    async with sessions.begin() as session:
        session.add(
            GoogleCalendarConnection(
                business_id=1,
                calendar_id="old-calendar",
                encrypted_refresh_token=old_ciphertext,
                scopes=["old-scope"],
            )
        )
    oauth.exchange_code.return_value = SimpleNamespace(
        refresh_token="new-refresh-token",
        scopes=[
            "https://www.googleapis.com/auth/calendar.events"
        ],
    )
    monkeypatch.setattr(
        google_integrations,
        "build_credential_cipher",
        lambda: cipher,
    )

    response = await client.get(
        "/api/v1/integrations/google/callback",
        params={
            "code": "reconnect-code",
            "state": "signed-state",
        },
    )

    assert response.status_code == 303
    async with sessions() as session:
        connection = await session.scalar(
            select(GoogleCalendarConnection)
        )
        assert connection.encrypted_refresh_token != old_ciphertext
        assert (
            cipher.decrypt(connection.encrypted_refresh_token)
            == "new-refresh-token"
        )
        assert connection.calendar_id == "primary"


async def test_first_google_connection_requires_refresh_token(
    booking_client,
    callback_dependencies,
):
    client, sessions, _ = booking_client
    _, oauth, cipher = callback_dependencies
    oauth.exchange_code.return_value = SimpleNamespace(
        refresh_token=None,
        scopes=[
            "https://www.googleapis.com/auth/calendar.events"
        ],
    )

    response = await client.get(
        "/api/v1/integrations/google/callback",
        params={
            "code": "first-code",
            "state": "signed-state",
        },
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "http://frontend.test/?google_calendar=error"
    )
    assert "first-code" not in response.headers["location"]
    assert "signed-state" not in response.headers["location"]
    cipher.encrypt.assert_not_called()
    async with sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(GoogleCalendarConnection)
        )
        assert count == 0
