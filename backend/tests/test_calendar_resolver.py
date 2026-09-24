from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from test_booking import booking_client  # noqa: F401

from app.models import Business, GoogleCalendarConnection
from app.services import calendar_resolver
from app.services.calendar_resolver import CalendarClientResolver


@pytest.fixture
def resolver_dependencies(monkeypatch):
    oauth_client = object()
    legacy_client = object()
    oauth_factory = Mock(return_value=oauth_client)
    legacy_factory = Mock(return_value=legacy_client)

    monkeypatch.setattr(
        calendar_resolver,
        "calendar_client_from_connection",
        oauth_factory,
    )
    monkeypatch.setattr(
        calendar_resolver,
        "calendar_client_from_token",
        legacy_factory,
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

    return oauth_client, legacy_client, oauth_factory, legacy_factory


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


async def set_legacy_calendar(sessions, calendar_id):
    async with sessions.begin() as session:
        business = await session.get(Business, 1)
        business.calendar_id = calendar_id


async def test_resolver_uses_oauth_without_legacy_calendar_id(
    booking_client,
    resolver_dependencies,
):
    _, sessions, _ = booking_client
    oauth_client, _, oauth_factory, legacy_factory = resolver_dependencies
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
    assert resolved.source == "oauth"
    oauth_factory.assert_called_once_with(
        encrypted_refresh_token="encrypted-token",
        scopes=["calendar.events"],
        cipher=cipher,
        client_id="client-id",
        client_secret="client-secret",
    )
    legacy_factory.assert_not_called()


async def test_resolver_prefers_oauth_over_legacy(
    booking_client,
    resolver_dependencies,
):
    _, sessions, _ = booking_client
    oauth_client, _, oauth_factory, legacy_factory = resolver_dependencies
    await set_legacy_calendar(sessions, "legacy-calendar")
    await add_connection(sessions)

    async with sessions() as session:
        resolved = await CalendarClientResolver(
            session,
            cipher=Mock(),
        ).resolve(1)

    assert resolved is not None
    assert resolved.client is oauth_client
    assert resolved.calendar_id == "primary"
    assert resolved.source == "oauth"
    oauth_factory.assert_called_once()
    legacy_factory.assert_not_called()


async def test_resolver_falls_back_to_legacy(
    booking_client,
    resolver_dependencies,
):
    _, sessions, _ = booking_client
    _, legacy_client, oauth_factory, legacy_factory = resolver_dependencies
    await set_legacy_calendar(sessions, "legacy-calendar")

    async with sessions() as session:
        resolved = await CalendarClientResolver(
            session,
            cipher=Mock(),
        ).resolve(1)

    assert resolved is not None
    assert resolved.client is legacy_client
    assert resolved.calendar_id == "legacy-calendar"
    assert resolved.source == "legacy"
    oauth_factory.assert_not_called()
    legacy_factory.assert_called_once_with(
        calendar_resolver.settings.google_calendar_token_file
    )


async def test_resolver_returns_none_without_any_calendar_configuration(
    booking_client,
    resolver_dependencies,
):
    _, sessions, _ = booking_client
    _, _, oauth_factory, legacy_factory = resolver_dependencies

    async with sessions() as session:
        resolved = await CalendarClientResolver(
            session,
            cipher=Mock(),
        ).resolve(1)

    assert resolved is None
    oauth_factory.assert_not_called()
    legacy_factory.assert_not_called()
