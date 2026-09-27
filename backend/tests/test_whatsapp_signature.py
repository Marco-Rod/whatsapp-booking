import hashlib
import hmac
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.api.v1 import whatsapp as whatsapp_api
from app.core.config import Settings
from app.integrations.whatsapp.client import WhatsAppConfigurationError
from app.integrations.whatsapp.signature import verify_webhook_signature
from app.main import app

SECRET = "test-app-secret"
BODY = b'{ "object" : "whatsapp_business_account", "entry" : [] }\n'
MAX_BODY_BYTES = 32


def sign(body):
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


async def post_without_content_length(chunks, headers=None, disconnect_after=False):
    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": disconnect_after or index < len(chunks) - 1,
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
            "path": "/api/v1/webhooks/whatsapp",
            "raw_path": b"/api/v1/webhooks/whatsapp",
            "query_string": b"",
            "headers": headers or [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        },
        receive,
        send,
    )
    return next(message["status"] for message in sent if message["type"] == "http.response.start")


def install_size_guard_dependencies(monkeypatch):
    session_calls = 0
    service_calls = 0

    async def processing_session():
        nonlocal session_calls
        session_calls += 1
        yield object()

    def create_service(session, config):
        nonlocal service_calls
        service_calls += 1
        return AsyncMock()

    monkeypatch.setattr(whatsapp_api, "get_session", processing_session)
    monkeypatch.setattr(whatsapp_api, "create_webhook_service", create_service)
    config = Settings(
        _env_file=None,
        meta_app_secret=SECRET,
        whatsapp_webhook_max_body_bytes=MAX_BODY_BYTES,
    )
    app.dependency_overrides[whatsapp_api.get_whatsapp_settings] = lambda: config
    return lambda: (session_calls, service_calls)


@pytest.mark.parametrize("signature", [None, "", "sha1=" + "a" * 64, "sha256=xyz", "sha256=" + "0" * 64])
def test_invalid_signatures(signature):
    with pytest.raises(PermissionError):
        verify_webhook_signature(BODY, signature, SECRET)


def test_correct_and_modified_body():
    verify_webhook_signature(BODY, sign(BODY), SECRET)
    with pytest.raises(PermissionError):
        verify_webhook_signature(BODY + b" ", sign(BODY), SECRET)


def test_missing_secret_fails_closed():
    with pytest.raises(WhatsAppConfigurationError):
        verify_webhook_signature(BODY, sign(BODY), "")


def test_webhook_body_limit_must_be_positive():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, whatsapp_webhook_max_body_bytes=0)


@pytest.mark.parametrize("case,status", [("valid",200),("missing",403),("wrong",403),
    ("modified",403),("unconfigured",503),("unsigned_bad_json",403),
    ("signed_bad_json",400),("signed_non_object",400)])
async def test_http_authenticates_before_processing(case, status, monkeypatch):
    service = AsyncMock()
    session_calls = 0
    config = Settings(_env_file=None, meta_app_secret="" if case == "unconfigured" else SECRET)

    async def processing_session():
        nonlocal session_calls
        session_calls += 1
        yield object()

    monkeypatch.setattr(whatsapp_api, "get_session", processing_session)
    monkeypatch.setattr(
        whatsapp_api,
        "create_webhook_service",
        lambda session, config: service,
    )
    app.dependency_overrides[whatsapp_api.get_whatsapp_settings] = lambda: config
    body = BODY
    signature = sign(body)
    if case in ("missing", "unsigned_bad_json"):
        signature = None
    if case == "wrong":
        signature = "sha256=" + "0" * 64
    if case == "modified":
        body += b" "
    if case in ("unsigned_bad_json", "signed_bad_json"):
        body = b"not-json"
        if case == "signed_bad_json":
            signature = sign(body)
    if case == "signed_non_object":
        body = b"[]"
        signature = sign(body)
    headers = {"X-Hub-Signature-256": signature} if signature else {}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/webhooks/whatsapp", content=body, headers=headers)
        assert response.status_code == status
        if status == 200:
            service.process.assert_awaited_once_with({"object":"whatsapp_business_account", "entry":[]})
            assert session_calls == 1
        else:
            service.process.assert_not_awaited()
            assert session_calls == 0
        assert SECRET not in response.text
    finally:
        app.dependency_overrides.pop(whatsapp_api.get_whatsapp_settings, None)


async def test_content_length_over_limit_rejects_before_hmac_or_session(monkeypatch):
    calls = install_size_guard_dependencies(monkeypatch)
    hmac_calls = 0

    def verify(*args):
        nonlocal hmac_calls
        hmac_calls += 1

    monkeypatch.setattr(whatsapp_api, "verify_webhook_signature", verify)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/webhooks/whatsapp",
                content=b"x" * (MAX_BODY_BYTES + 1),
            )
        assert response.status_code == 413
        assert hmac_calls == 0
        assert calls() == (0, 0)
    finally:
        app.dependency_overrides.pop(whatsapp_api.get_whatsapp_settings, None)


async def test_chunked_body_over_limit_rejects_before_hmac_or_session(monkeypatch):
    calls = install_size_guard_dependencies(monkeypatch)
    hmac_calls = 0

    def verify(*args):
        nonlocal hmac_calls
        hmac_calls += 1

    monkeypatch.setattr(whatsapp_api, "verify_webhook_signature", verify)
    try:
        status = await post_without_content_length([
            b"x" * MAX_BODY_BYTES,
            b"x",
        ])
        assert status == 413
        assert hmac_calls == 0
        assert calls() == (0, 0)
    finally:
        app.dependency_overrides.pop(whatsapp_api.get_whatsapp_settings, None)


async def test_interrupted_body_rejects_before_hmac_or_session(monkeypatch):
    calls = install_size_guard_dependencies(monkeypatch)
    hmac_calls = 0

    def verify(*args):
        nonlocal hmac_calls
        hmac_calls += 1

    monkeypatch.setattr(whatsapp_api, "verify_webhook_signature", verify)
    try:
        status = await post_without_content_length(
            [b"partial"],
            disconnect_after=True,
        )
        assert status == 400
        assert hmac_calls == 0
        assert calls() == (0, 0)
    finally:
        app.dependency_overrides.pop(whatsapp_api.get_whatsapp_settings, None)


async def test_body_at_limit_reaches_hmac_without_acquiring_session(monkeypatch):
    calls = install_size_guard_dependencies(monkeypatch)
    body = b"x" * MAX_BODY_BYTES
    hmac_calls = []

    def verify(received_body, signature, secret):
        hmac_calls.append((received_body, signature, secret))

    monkeypatch.setattr(whatsapp_api, "verify_webhook_signature", verify)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/webhooks/whatsapp",
                content=body,
                headers={"X-Hub-Signature-256": sign(body)},
            )
        assert response.status_code == 400
        assert hmac_calls == [(body, sign(body), SECRET)]
        assert calls() == (0, 0)
    finally:
        app.dependency_overrides.pop(whatsapp_api.get_whatsapp_settings, None)


async def test_signed_webhook_closes_session_generator_after_success(monkeypatch):
    events = []
    service = AsyncMock()

    async def processing_session():
        events.append("acquired")
        try:
            yield object()
        finally:
            events.append("closed")

    monkeypatch.setattr(whatsapp_api, "get_session", processing_session)
    monkeypatch.setattr(
        whatsapp_api,
        "create_webhook_service",
        lambda session, config: service,
    )

    await whatsapp_api.process_signed_webhook({"entry": []}, object())

    service.process.assert_awaited_once_with({"entry": []})
    assert events == ["acquired", "closed"]


@pytest.mark.parametrize("failure", ["construction", "processing"])
async def test_signed_webhook_closes_session_generator_after_failure(
    monkeypatch,
    failure,
):
    events = []

    async def processing_session():
        events.append("acquired")
        try:
            yield object()
        finally:
            events.append("closed")

    def create_service(session, config):
        if failure == "construction":
            raise RuntimeError("construction failed")
        service = AsyncMock()
        service.process.side_effect = RuntimeError("processing failed")
        return service

    monkeypatch.setattr(whatsapp_api, "get_session", processing_session)
    monkeypatch.setattr(whatsapp_api, "create_webhook_service", create_service)

    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        await whatsapp_api.process_signed_webhook({"entry": []}, object())

    assert events == ["acquired", "closed"]
