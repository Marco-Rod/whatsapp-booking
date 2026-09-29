import json

import httpx
import pytest
from pydantic import SecretStr

from app.integrations.whatsapp.embedded_signup_token_inspection import (
    MetaEmbeddedSignupTokenAppMismatchError,
    MetaEmbeddedSignupTokenInspectionContentEncodingError,
    MetaEmbeddedSignupTokenInspectionJSONError,
    MetaEmbeddedSignupTokenInspectionResponseTooLargeError,
    MetaEmbeddedSignupTokenInspectionSchemaError,
    MetaEmbeddedSignupTokenInspectionTimeoutError,
    MetaEmbeddedSignupTokenInspectionTransportError,
    MetaEmbeddedSignupTokenInspectionUpstreamError,
    MetaEmbeddedSignupTokenInvalidError,
    MetaEmbeddedSignupTokenInspector,
)


FAKE_APP_ID = "test-app-id"
FAKE_PROVIDER_TOKEN = "test-provider-debug-token-not-real"
FAKE_EMBEDDED_TOKEN = "test-embedded-signup-token-not-real"


class ControlledAsyncByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks=(), error=None):
        self.chunks = list(chunks)
        self.error = error
        self.read_count = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk
        if self.error is not None:
            raise self.error

    async def aclose(self):
        self.closed = True


def make_inspector(handler, *, maximum_bytes=16_384, app_id=FAKE_APP_ID):
    return MetaEmbeddedSignupTokenInspector(
        app_id=app_id,
        provider_debug_token=SecretStr(FAKE_PROVIDER_TOKEN),
        graph_version="v25.0",
        max_response_bytes=maximum_bytes,
        transport=httpx.MockTransport(handler),
    )


def response(payload, *, status=200, headers=None, stream=None):
    response_headers = {"content-type": "application/json"}
    if headers:
        response_headers.update(headers)
    return httpx.Response(
        status,
        headers=response_headers,
        stream=stream
        or ControlledAsyncByteStream([json.dumps(payload).encode()]),
    )


def valid_data(**extra):
    return {"data": {"is_valid": True, "app_id": FAKE_APP_ID, **extra}}


async def test_inspection_constructs_exact_debug_token_request_once():
    requests = []

    def handler(request):
        requests.append(request)
        return response(valid_data())

    result = await make_inspector(handler).inspect_token(SecretStr(FAKE_EMBEDDED_TOKEN))

    assert result.app_id == FAKE_APP_ID
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url.copy_with(query=None)) == (
        "https://graph.facebook.com/v25.0/debug_token"
    )
    assert request.url.params.get("input_token") == FAKE_EMBEDDED_TOKEN
    assert list(request.url.params.keys()) == ["input_token"]
    assert request.headers["authorization"] == f"Bearer {FAKE_PROVIDER_TOKEN}"
    assert request.headers["accept-encoding"] == "identity"


async def test_inspection_accepts_minimal_valid_response_and_optional_fields_absent():
    result = await make_inspector(lambda request: response(valid_data())).inspect_token(
        FAKE_EMBEDDED_TOKEN
    )
    assert result.token_type is None
    assert result.expires_at is None
    assert result.data_access_expires_at is None
    assert result.scopes == ()
    assert result.granular_scopes == ()


async def test_inspection_accepts_integer_app_id_when_it_matches_safely():
    result = await make_inspector(
        lambda request: response({"data": {"is_valid": True, "app_id": 123}}),
        app_id="123",
    ).inspect_token(FAKE_EMBEDDED_TOKEN)
    # A separate inspector models the configured ID as a string, as Settings does.
    assert result.app_id == "123"


async def test_inspection_rejects_invalid_token():
    with pytest.raises(MetaEmbeddedSignupTokenInvalidError):
        await make_inspector(
            lambda request: response({"data": {"is_valid": False, "app_id": FAKE_APP_ID}})
        ).inspect_token(FAKE_EMBEDDED_TOKEN)


async def test_inspection_rejects_app_id_mismatch():
    with pytest.raises(MetaEmbeddedSignupTokenAppMismatchError):
        await make_inspector(
            lambda request: response({"data": {"is_valid": True, "app_id": "other-app"}})
        ).inspect_token(FAKE_EMBEDDED_TOKEN)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"data": {"app_id": FAKE_APP_ID}},
        {"data": {"is_valid": "true", "app_id": FAKE_APP_ID}},
        {"data": {"is_valid": True}},
        {"data": {"is_valid": True, "app_id": True}},
    ],
)
async def test_inspection_rejects_malformed_required_schema(payload):
    with pytest.raises(MetaEmbeddedSignupTokenInspectionSchemaError):
        await make_inspector(lambda request: response(payload)).inspect_token(
            FAKE_EMBEDDED_TOKEN
        )


async def test_inspection_parses_scopes_targets_and_expiries_without_enforcing_policy():
    result = await make_inspector(
        lambda request: response(
            valid_data(
                type="USER",
                expires_at=0,
                data_access_expires_at=1234567890,
                scopes=["whatsapp_business_management", "business_management"],
                granular_scopes=[
                    {
                        "scope": "whatsapp_business_management",
                        "target_ids": ["candidate-waba-id"],
                    },
                    {"scope": "business_management"},
                ],
            )
        )
    ).inspect_token(FAKE_EMBEDDED_TOKEN)
    assert result.token_type == "USER"
    assert result.expires_at == 0
    assert result.data_access_expires_at == 1234567890
    assert result.has_scope("whatsapp_business_management")
    assert not result.has_scope("missing")
    assert result.target_ids_for_scope("whatsapp_business_management") == (
        "candidate-waba-id",
    )
    assert result.target_ids_for_scope("business_management") == ()


@pytest.mark.parametrize(
    "extra",
    [
        {"type": 1},
        {"expires_at": "tomorrow"},
        {"data_access_expires_at": -1},
        {"scopes": ["valid", 1]},
        {"granular_scopes": {}},
        {"granular_scopes": [{"scope": 1}]},
        {"granular_scopes": [{"scope": "valid", "target_ids": [1]}]},
    ],
)
async def test_inspection_rejects_malformed_optional_schema(extra):
    with pytest.raises(MetaEmbeddedSignupTokenInspectionSchemaError):
        await make_inspector(lambda request: response(valid_data(**extra))).inspect_token(
            FAKE_EMBEDDED_TOKEN
        )


async def test_inspection_rejects_malformed_json():
    with pytest.raises(MetaEmbeddedSignupTokenInspectionJSONError):
        await make_inspector(
            lambda request: response({}, stream=ControlledAsyncByteStream([b"not-json"]))
        ).inspect_token(FAKE_EMBEDDED_TOKEN)


@pytest.mark.parametrize("status", [400, 429, 500])
async def test_inspection_sanitizes_http_errors_without_retry(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, content=b'{"error":"provider-secret"}')

    with pytest.raises(MetaEmbeddedSignupTokenInspectionUpstreamError) as error:
        await make_inspector(handler).inspect_token(FAKE_EMBEDDED_TOKEN)
    assert error.value.status_code == status
    assert len(calls) == 1
    assert "provider-secret" not in str(error.value)
    assert FAKE_EMBEDDED_TOKEN not in str(error.value)
    assert FAKE_PROVIDER_TOKEN not in str(error.value)


async def test_inspection_sanitizes_timeout_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("provider-secret", request=request)

    with pytest.raises(MetaEmbeddedSignupTokenInspectionTimeoutError) as error:
        await make_inspector(handler).inspect_token(FAKE_EMBEDDED_TOKEN)
    assert len(calls) == 1
    assert FAKE_EMBEDDED_TOKEN not in str(error.value)
    assert FAKE_PROVIDER_TOKEN not in str(error.value)


async def test_inspection_sanitizes_transport_error_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("provider-secret", request=request)

    with pytest.raises(MetaEmbeddedSignupTokenInspectionTransportError) as error:
        await make_inspector(handler).inspect_token(FAKE_EMBEDDED_TOKEN)
    assert len(calls) == 1
    assert FAKE_EMBEDDED_TOKEN not in str(error.value)
    assert FAKE_PROVIDER_TOKEN not in str(error.value)


async def test_inspection_rejects_oversized_stream_without_consuming_remainder():
    body = json.dumps(valid_data()).encode()
    stream = ControlledAsyncByteStream([body[:8], body[8:], b"must-not-be-read"])
    with pytest.raises(MetaEmbeddedSignupTokenInspectionResponseTooLargeError):
        await make_inspector(
            lambda request: response({}, stream=stream),
            maximum_bytes=len(body) - 1,
        ).inspect_token(FAKE_EMBEDDED_TOKEN)
    assert stream.read_count == 2
    assert stream.closed


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "unknown"])
async def test_inspection_rejects_compressed_or_unknown_content_encoding(encoding):
    stream = ControlledAsyncByteStream([b"must-not-be-read"])
    with pytest.raises(MetaEmbeddedSignupTokenInspectionContentEncodingError):
        await make_inspector(
            lambda request: response(
                {},
                headers={"content-encoding": encoding},
                stream=stream,
            )
        ).inspect_token(FAKE_EMBEDDED_TOKEN)
    assert stream.read_count == 0
    assert stream.closed


async def test_inspection_does_not_follow_redirects_or_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://example.test/elsewhere"})

    with pytest.raises(MetaEmbeddedSignupTokenInspectionUpstreamError):
        await make_inspector(handler).inspect_token(FAKE_EMBEDDED_TOKEN)
    assert len(calls) == 1


async def test_inspection_sanitizes_stream_request_error_without_retry():
    stream = ControlledAsyncByteStream(error=httpx.DecodingError("provider-secret"))
    with pytest.raises(MetaEmbeddedSignupTokenInspectionTransportError) as error:
        await make_inspector(
            lambda request: response({}, stream=stream)
        ).inspect_token(FAKE_EMBEDDED_TOKEN)
    assert stream.closed
    assert FAKE_EMBEDDED_TOKEN not in str(error.value)
    assert FAKE_PROVIDER_TOKEN not in str(error.value)


async def test_inspection_errors_never_include_query_or_credentials(caplog):
    with pytest.raises(MetaEmbeddedSignupTokenInspectionSchemaError) as error:
        await make_inspector(lambda request: response({})).inspect_token(
            FAKE_EMBEDDED_TOKEN
        )
    rendered = f"{error.value!r} {error.value}"
    assert FAKE_EMBEDDED_TOKEN not in rendered
    assert FAKE_PROVIDER_TOKEN not in rendered
    assert FAKE_APP_ID not in rendered
    assert FAKE_EMBEDDED_TOKEN not in caplog.text
    assert FAKE_PROVIDER_TOKEN not in caplog.text


async def test_inspection_sets_trust_env_false(monkeypatch):
    observed = {}
    original_client = httpx.AsyncClient

    def capturing_client(*args, **kwargs):
        observed.update(kwargs)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(
        "app.integrations.whatsapp.embedded_signup_token_inspection.httpx.AsyncClient",
        capturing_client,
    )
    await make_inspector(lambda request: response(valid_data())).inspect_token(
        FAKE_EMBEDDED_TOKEN
    )
    assert observed["trust_env"] is False
