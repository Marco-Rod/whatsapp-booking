import asyncio
import threading
from unittest.mock import MagicMock

import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from httplib2 import Response

from app.integrations.google_calendar.client import GoogleCalendarClient
from app.integrations.google_calendar.errors import GoogleCalendarError


def sdk():
    service = MagicMock()
    service.__enter__.return_value = service
    return service


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_contract_and_worker_thread(operation):
    main_thread = threading.get_ident()
    threads = []
    service = sdk()
    method = {"create": "insert", "update": "update", "delete": "delete"}[operation]
    request = getattr(service.events.return_value, method)

    def execute(**kwargs):
        threads.append(threading.get_ident())
        return {"id": "event-123"}

    request.return_value.execute.side_effect = execute

    def factory():
        threads.append(threading.get_ident())
        return service

    service.__exit__.side_effect = lambda *args: threads.append(threading.get_ident())
    client = GoogleCalendarClient(factory)
    body = {"summary": "Test", "start": {"dateTime": "2026-09-17T12:00:00-06:00"}}
    expected = {"calendarId": "business-calendar"}
    if operation == "create":
        result = await client.create_event("business-calendar", body)
    elif operation == "update":
        result = await client.update_event("business-calendar", "event-123", body)
    else:
        result = await client.delete_event("business-calendar", "event-123")
    if operation != "create":
        expected["eventId"] = "event-123"
    if operation != "delete":
        expected["body"] = body
    request.assert_called_once_with(**expected)
    request.return_value.execute.assert_called_once_with(num_retries=0)
    assert result == (None if operation == "delete" else "event-123")
    assert len(threads) == 3 and len(set(threads)) == 1
    assert threads[0] != main_thread


@pytest.mark.parametrize("status", [401, 403, 404, 409, 410, 429, 500, 503])
async def test_http_errors_are_sanitized_without_retries(status):
    service = sdk()
    execute = service.events.return_value.delete.return_value.execute
    execute.side_effect = HttpError(Response({"status": status}), b'sensitive response')
    with pytest.raises(GoogleCalendarError) as error:
        await GoogleCalendarClient(lambda: service).delete_event("calendar", "event")
    assert error.value.status_code == status
    assert error.value.operation == "delete"
    assert "sensitive" not in str(error.value)
    execute.assert_called_once_with(num_retries=0)
    service.__exit__.assert_called_once()


@pytest.mark.parametrize("failure", [TimeoutError("secret"), RefreshError("secret")])
async def test_transport_and_auth_errors(failure):
    service = sdk()
    service.events.return_value.insert.return_value.execute.side_effect = failure
    with pytest.raises(GoogleCalendarError) as error:
        await GoogleCalendarClient(lambda: service).create_event("calendar", {})
    assert error.value.status_code is None
    assert "secret" not in str(error.value)
    service.__exit__.assert_called_once()


@pytest.mark.parametrize("response", [None, {}, {"id": ""}, {"id": 123}])
async def test_create_requires_event_id(response):
    service = sdk()
    service.events.return_value.insert.return_value.execute.return_value = response
    with pytest.raises(GoogleCalendarError):
        await GoogleCalendarClient(lambda: service).create_event("calendar", {})


async def test_concurrent_requests_use_separate_services_and_keep_loop_responsive():
    started = threading.Event()
    release = threading.Event()
    services = []

    def factory():
        service = sdk()
        services.append(service)

        def execute(**kwargs):
            started.set()
            if not release.wait(timeout=3):
                raise TimeoutError("event loop was blocked")
            return {"id": "created"}

        service.events.return_value.insert.return_value.execute.side_effect = execute
        return service

    client = GoogleCalendarClient(factory)
    first = asyncio.create_task(client.create_event("calendar", {}))
    second = asyncio.create_task(client.create_event("calendar", {}))
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(0.01)
        release.set()
        assert await asyncio.gather(first, second) == ["created", "created"]
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
    assert len(services) == 2 and services[0] is not services[1]


async def test_missing_oauth_file_is_a_calendar_error(tmp_path):
    from app.integrations.google_calendar.factory import calendar_client_from_token

    client = calendar_client_from_token(str(tmp_path / "missing-token.json"))
    with pytest.raises(GoogleCalendarError) as error:
        await client.create_event("primary", {})
    assert error.value.operation == "credentials"


async def test_token_factory_uses_fresh_credentials_and_bounded_transport(monkeypatch):
    from app.integrations.google_calendar import factory

    credentials = MagicMock(side_effect=lambda *args: object())
    transport = MagicMock(side_effect=lambda **kwargs: MagicMock())
    authorized = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    build = MagicMock(side_effect=lambda *args, **kwargs: sdk())
    monkeypatch.setattr(factory.Credentials, "from_authorized_user_file", credentials)
    monkeypatch.setattr(factory.httplib2, "Http", transport)
    monkeypatch.setattr(factory, "AuthorizedHttp", authorized)
    monkeypatch.setattr(factory, "build", build)
    client = factory.calendar_client_from_token("test-token.json")
    await asyncio.gather(client.delete_event("primary", "a"), client.delete_event("primary", "b"))
    assert credentials.call_count == authorized.call_count == build.call_count == 2
    assert authorized.call_args_list[0].args[0] is not authorized.call_args_list[1].args[0]
    assert all(call.kwargs == {"timeout": 20} for call in transport.call_args_list)
    assert all(call.kwargs["static_discovery"] for call in build.call_args_list)


async def test_connection_factory_decrypts_lazily_and_uses_bounded_transport(
    monkeypatch,
):
    from app.integrations.google_calendar import factory

    cipher = MagicMock()
    cipher.decrypt.return_value = "real-refresh-token"

    credentials = MagicMock(side_effect=lambda **kwargs: object())
    transport = MagicMock(side_effect=lambda **kwargs: MagicMock())
    authorized = MagicMock(side_effect=lambda *args, **kwargs: MagicMock())
    build = MagicMock(side_effect=lambda *args, **kwargs: sdk())

    monkeypatch.setattr(factory, "Credentials", credentials)
    monkeypatch.setattr(factory.httplib2, "Http", transport)
    monkeypatch.setattr(factory, "AuthorizedHttp", authorized)
    monkeypatch.setattr(factory, "build", build)

    client = factory.calendar_client_from_connection(
        encrypted_refresh_token="encrypted-refresh-token",
        scopes=[
            "https://www.googleapis.com/auth/calendar.events"
        ],
        cipher=cipher,
        client_id="client-id",
        client_secret="client-secret",
    )

    # Building the dependency must not expose the refresh token yet.
    cipher.decrypt.assert_not_called()

    await client.delete_event("primary", "event-id")

    cipher.decrypt.assert_called_once_with(
        "encrypted-refresh-token"
    )

    credentials.assert_called_once_with(
        token=None,
        refresh_token="real-refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client-id",
        client_secret="client-secret",
        scopes=[
            "https://www.googleapis.com/auth/calendar.events"
        ],
    )

    assert transport.call_args.kwargs == {
        "timeout": 20
    }

    assert build.call_args.args[:2] == (
        "calendar",
        "v3",
    )

    assert build.call_args.kwargs[
        "cache_discovery"
    ] is False

    assert build.call_args.kwargs[
        "static_discovery"
    ] is True


async def test_connection_factory_maps_decryption_failure_to_calendar_error(
    monkeypatch,
):
    from app.integrations.google_calendar import factory
    from app.security.credentials import (
        CredentialDecryptionError,
    )

    cipher = MagicMock()
    cipher.decrypt.side_effect = CredentialDecryptionError(
        "invalid ciphertext"
    )

    client = factory.calendar_client_from_connection(
        encrypted_refresh_token="invalid-ciphertext",
        scopes=[
            "https://www.googleapis.com/auth/calendar.events"
        ],
        cipher=cipher,
        client_id="client-id",
        client_secret="client-secret",
    )

    with pytest.raises(GoogleCalendarError) as error:
        await client.create_event("primary", {})

    assert error.value.operation == "credentials"


@pytest.mark.parametrize(
    ("encrypted_refresh_token", "scopes", "client_id", "client_secret"),
    [
        ("", ["scope"], "client-id", "client-secret"),
        ("encrypted", [], "client-id", "client-secret"),
        ("encrypted", ["scope"], "", "client-secret"),
        ("encrypted", ["scope"], "client-id", ""),
    ],
)
async def test_connection_factory_rejects_incomplete_credentials(
    encrypted_refresh_token,
    scopes,
    client_id,
    client_secret,
):
    from app.integrations.google_calendar import factory

    cipher = MagicMock()

    with pytest.raises(GoogleCalendarError) as error:
        factory.calendar_client_from_connection(
            encrypted_refresh_token=encrypted_refresh_token,
            scopes=scopes,
            cipher=cipher,
            client_id=client_id,
            client_secret=client_secret,
        )

    assert error.value.operation == "credentials"
    cipher.decrypt.assert_not_called()
