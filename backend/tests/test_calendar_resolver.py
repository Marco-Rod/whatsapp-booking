from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from test_booking import booking_client  # noqa: F401

from app.models import GoogleCalendarConnection
from app.services import calendar_resolver
from app.services.calendar_resolver import CalendarClientResolver


@pytest.fixture
def resolver_dependencies(monkeypatch):
    oauth_client = object()
    oauth_factory = Mock(return_value=oauth_client)

    monkeypatch.setattr(
        calendar_resolver,
        "calendar_client_from_connection",
        oauth_factory,
    )
    monkeypatch.setattr(
        calendar_resolver.settings,
        "google_oauth_client_id",
        SecretStr("client-id"),
    )
    monkeypatch.setattr(
        calendar_resolver.settings,
        "google_oauth_client_secret",
        SecretStr("client-secret"),
    )

    return oauth_client, oauth_factory


async def add_connection(sessions, *, business_id=1):
    async with sessions.begin() as session:
        session.add(
            GoogleCalendarConnection(
                business_id=business_id,
                calendar_id="primary",
                encrypted_refresh_token="encrypted-token",
                scopes=["calendar.events"],
            )
        )


async def test_resolver_uses_oauth_connection(
    booking_client,
    resolver_dependencies,
):
    _, sessions, _ = booking_client
    oauth_client, oauth_factory = resolver_dependencies
    cipher = Mock()
    await add_connection(sessions)

    async with sessions() as session:
        resolved = await CalendarClientResolver(
            session,
            cipher=cipher,
        ).resolve(1)

    assert resolved is not None
    assert resolved.calendar_id == "primary"
    assert resolved.client is oauth_client
    oauth_factory.assert_called_once_with(
        encrypted_refresh_token="encrypted-token",
        scopes=["calendar.events"],
        cipher=cipher,
        client_id="client-id",
        client_secret="client-secret",
    )


async def test_resolver_returns_none_without_oauth_connection(
    booking_client,
    resolver_dependencies,
):
    _, sessions, _ = booking_client
    _, oauth_factory = resolver_dependencies

    async with sessions() as session:
        resolved = await CalendarClientResolver(
            session,
            cipher=Mock(),
        ).resolve(1)

    assert resolved is None
    oauth_factory.assert_not_called()
