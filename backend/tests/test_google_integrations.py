from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from test_booking import booking_client  # noqa: F401

from app.api.v1 import google_integrations
from app.integrations.google_calendar.oauth import GoogleOAuthExchangeError
from app.models import GoogleCalendarConnection
from app.security.oauth_state import OAuthStateError


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

    return state_manager, oauth, cipher


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

    assert response.status_code == 200
    assert response.json() == {
        "status": "connected",
        "business_id": 1,
    }

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

    assert first.status_code == 200

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

    assert second.status_code == 200

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

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Unable to complete Google OAuth"
    }

    cipher.encrypt.assert_not_called()

    async with sessions() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(GoogleCalendarConnection)
        )

        assert count == 0
