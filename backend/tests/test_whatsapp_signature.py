import hashlib
import hmac
from unittest.mock import AsyncMock

import httpx
import pytest

from app.api.v1.whatsapp import get_webhook_service, get_whatsapp_settings
from app.core.config import Settings
from app.integrations.whatsapp.client import WhatsAppConfigurationError
from app.integrations.whatsapp.signature import verify_webhook_signature
from app.main import app

SECRET = "test-app-secret"
BODY = b'{ "object" : "whatsapp_business_account", "entry" : [] }\n'


def sign(body):
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


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


@pytest.mark.parametrize("case,status", [("valid",200),("missing",403),("wrong",403),
    ("modified",403),("unconfigured",503),("unsigned_bad_json",403),
    ("signed_bad_json",400),("signed_non_object",400)])
async def test_http_authenticates_before_processing(case, status):
    service = AsyncMock()
    config = Settings(_env_file=None, meta_app_secret="" if case == "unconfigured" else SECRET)
    app.dependency_overrides[get_webhook_service] = lambda: service
    app.dependency_overrides[get_whatsapp_settings] = lambda: config
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
        else:
            service.process.assert_not_awaited()
        assert SECRET not in response.text
    finally:
        app.dependency_overrides.pop(get_webhook_service, None)
        app.dependency_overrides.pop(get_whatsapp_settings, None)
