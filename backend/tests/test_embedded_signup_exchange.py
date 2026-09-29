import json

import httpx
import pytest
from pydantic import SecretStr

from app.integrations.whatsapp.embedded_signup_exchange import (
    MetaEmbeddedSignupExchangeClient,
    MetaEmbeddedSignupExchangeContentEncodingError,
    MetaEmbeddedSignupExchangeContentTypeError,
    MetaEmbeddedSignupExchangeJSONError,
    MetaEmbeddedSignupExchangeResponseError,
    MetaEmbeddedSignupExchangeResponseTooLargeError,
    MetaEmbeddedSignupExchangeTimeoutError,
    MetaEmbeddedSignupExchangeTransportError,
    MetaEmbeddedSignupExchangeUpstreamError,
)


FAKE_APP_ID = "test-app-id"
FAKE_SECRET = "test-app-secret-not-real"
FAKE_REDIRECT_URI = "https://example.test/meta/embedded-signup"
FAKE_CODE = "test-authorization-code-not-real"
FAKE_TOKEN = "test-access-token-not-real"


def make_client(handler, *, maximum_bytes=16_384):
    return MetaEmbeddedSignupExchangeClient(
        app_id=FAKE_APP_ID,
        app_secret=SecretStr(FAKE_SECRET),
        redirect_uri=FAKE_REDIRECT_URI,
        graph_version="v25.0",
        max_response_bytes=maximum_bytes,
        transport=httpx.MockTransport(handler),
    )


def json_response(payload, *, status=200, headers=None):
    response_headers = {"content-type": "application/json"}
    if headers:
        response_headers.update(headers)
    return httpx.Response(
        status,
        headers=response_headers,
        stream=ControlledAsyncByteStream([json.dumps(payload).encode()]),
    )


class ControlledAsyncByteStream(httpx.AsyncByteStream):
    """Expose exact raw chunks and prove the client stops consuming early."""

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


def streamed_response(stream, *, headers=None, status=200):
    response_headers = {"content-type": "application/json"}
    if headers:
        response_headers.update(headers)
    return httpx.Response(status, headers=response_headers, stream=stream)


async def test_exchange_constructs_exact_observed_request_once():
    requests = []

    def handler(request):
        requests.append(request)
        return json_response({"access_token": FAKE_TOKEN})

    result = await make_client(handler).exchange_authorization_code(
        SecretStr(FAKE_CODE)
    )

    assert result.access_token.get_secret_value() == FAKE_TOKEN
    assert repr(result).count(FAKE_TOKEN) == 0
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://graph.facebook.com/v25.0/oauth/access_token"
    assert request.url.query == b""
    assert request.headers["content-type"] == "application/json"
    assert request.headers["accept-encoding"] == "identity"
    assert json.loads(request.content) == {
        "client_id": FAKE_APP_ID,
        "client_secret": FAKE_SECRET,
        "code": FAKE_CODE,
        "grant_type": "authorization_code",
        "redirect_uri": FAKE_REDIRECT_URI,
    }
    assert b"config_id" not in request.content
    assert b"code_verifier" not in request.content


async def test_exchange_accepts_unknown_response_fields_without_inventing_semantics():
    result = await make_client(
        lambda request: json_response(
            {"access_token": FAKE_TOKEN, "undocumented": "ignored"}
        )
    ).exchange_authorization_code(FAKE_CODE)
    assert result.access_token.get_secret_value() == FAKE_TOKEN
    assert result.__dict__.keys() == {"access_token"}


@pytest.mark.parametrize(
    "payload",
    [{}, {"access_token": ""}, {"access_token": "   "}, {"access_token": 12}],
)
async def test_exchange_rejects_missing_or_invalid_access_token(payload):
    with pytest.raises(MetaEmbeddedSignupExchangeResponseError):
        await make_client(lambda request: json_response(payload)).exchange_authorization_code(
            FAKE_CODE
        )


async def test_exchange_rejects_malformed_json():
    with pytest.raises(MetaEmbeddedSignupExchangeJSONError):
        await make_client(
            lambda request: streamed_response(
                ControlledAsyncByteStream([b"not-json"]),
            )
        ).exchange_authorization_code(FAKE_CODE)


async def test_exchange_rejects_non_json_content_type_without_reading_contract():
    with pytest.raises(MetaEmbeddedSignupExchangeContentTypeError):
        await make_client(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"not-json",
            )
        ).exchange_authorization_code(FAKE_CODE)


async def test_exchange_accepts_response_exactly_at_size_boundary():
    body = json.dumps({"access_token": "x"}).encode()
    stream = ControlledAsyncByteStream([body])
    result = await make_client(
        lambda request: streamed_response(stream),
        maximum_bytes=len(body),
    ).exchange_authorization_code(FAKE_CODE)
    assert result.access_token.get_secret_value() == "x"
    assert stream.read_count == 1
    assert stream.closed


async def test_exchange_rejects_response_over_size_boundary():
    body = json.dumps({"access_token": "x"}).encode()
    stream = ControlledAsyncByteStream([body, b"must-not-be-read"])
    with pytest.raises(MetaEmbeddedSignupExchangeResponseTooLargeError):
        await make_client(
            lambda request: streamed_response(stream),
            maximum_bytes=len(body) - 1,
        ).exchange_authorization_code(FAKE_CODE)
    assert stream.read_count == 1
    assert stream.closed


async def test_exchange_rejects_content_length_over_limit_without_consuming_body():
    stream = ControlledAsyncByteStream([b"must-not-be-read"])
    with pytest.raises(MetaEmbeddedSignupExchangeResponseTooLargeError):
        await make_client(
            lambda request: streamed_response(
                stream,
                headers={"content-length": "17"},
            ),
            maximum_bytes=16,
        ).exchange_authorization_code(FAKE_CODE)
    assert stream.read_count == 0
    assert stream.closed


async def test_exchange_ignores_malformed_content_length_and_streams_safely():
    body = json.dumps({"access_token": "x"}).encode()
    stream = ControlledAsyncByteStream([body])
    result = await make_client(
        lambda request: streamed_response(
            stream,
            headers={"content-length": "not-a-number"},
        ),
        maximum_bytes=len(body),
    ).exchange_authorization_code(FAKE_CODE)
    assert result.access_token.get_secret_value() == "x"
    assert stream.read_count == 1


async def test_exchange_rejects_chunked_stream_after_limit_without_consuming_remainder():
    body = json.dumps({"access_token": "x"}).encode()
    stream = ControlledAsyncByteStream([body[:8], body[8:], b"must-not-be-read"])
    with pytest.raises(MetaEmbeddedSignupExchangeResponseTooLargeError):
        await make_client(
            lambda request: streamed_response(stream),
            maximum_bytes=len(body) - 1,
        ).exchange_authorization_code(FAKE_CODE)
    assert stream.read_count == 2
    assert stream.closed


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "unknown"])
async def test_exchange_rejects_compressed_or_unknown_content_encoding_without_consuming(
    encoding,
):
    stream = ControlledAsyncByteStream([b"must-not-be-read"])
    with pytest.raises(MetaEmbeddedSignupExchangeContentEncodingError):
        await make_client(
            lambda request: streamed_response(
                stream,
                headers={"content-encoding": encoding},
            )
        ).exchange_authorization_code(FAKE_CODE)
    assert stream.read_count == 0
    assert stream.closed


@pytest.mark.parametrize("code", ["", "x" * 4_097])
async def test_exchange_rejects_invalid_code_before_transport(code):
    calls = []

    def handler(request):
        calls.append(request)
        return json_response({"access_token": FAKE_TOKEN})

    with pytest.raises(MetaEmbeddedSignupExchangeResponseError):
        await make_client(handler).exchange_authorization_code(code)
    assert calls == []


@pytest.mark.parametrize("status", [400, 429, 500])
async def test_exchange_sanitizes_http_errors_without_retry(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, content=b'{"error":"provider-secret"}')

    with pytest.raises(MetaEmbeddedSignupExchangeUpstreamError) as error:
        await make_client(handler).exchange_authorization_code(FAKE_CODE)
    assert error.value.status_code == status
    assert len(calls) == 1
    assert "provider-secret" not in str(error.value)
    assert FAKE_CODE not in str(error.value)
    assert FAKE_SECRET not in str(error.value)


async def test_exchange_sanitizes_connect_failure_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("provider-secret", request=request)

    with pytest.raises(MetaEmbeddedSignupExchangeTransportError) as error:
        await make_client(handler).exchange_authorization_code(FAKE_CODE)
    assert len(calls) == 1
    assert "provider-secret" not in str(error.value)
    assert FAKE_CODE not in str(error.value)


async def test_exchange_sanitizes_timeout_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("provider-secret", request=request)

    with pytest.raises(MetaEmbeddedSignupExchangeTimeoutError) as error:
        await make_client(handler).exchange_authorization_code(FAKE_CODE)
    assert len(calls) == 1
    assert "provider-secret" not in str(error.value)
    assert FAKE_CODE not in str(error.value)


async def test_exchange_does_not_follow_redirects():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://example.test/elsewhere"})

    with pytest.raises(MetaEmbeddedSignupExchangeUpstreamError) as error:
        await make_client(handler).exchange_authorization_code(FAKE_CODE)
    assert error.value.status_code == 302
    assert len(calls) == 1


async def test_exchange_sanitizes_stream_decoding_error_without_retry():
    stream = ControlledAsyncByteStream(
        error=httpx.DecodingError("provider-secret")
    )
    with pytest.raises(MetaEmbeddedSignupExchangeTransportError) as error:
        await make_client(
            lambda request: streamed_response(stream)
        ).exchange_authorization_code(FAKE_CODE)
    assert "provider-secret" not in str(error.value)
    assert FAKE_CODE not in str(error.value)
    assert stream.closed


async def test_exchange_sanitizes_stream_request_error_without_retry():
    stream = ControlledAsyncByteStream(
        error=httpx.ReadError("provider-secret")
    )
    with pytest.raises(MetaEmbeddedSignupExchangeTransportError) as error:
        await make_client(
            lambda request: streamed_response(stream)
        ).exchange_authorization_code(FAKE_CODE)
    assert "provider-secret" not in str(error.value)
    assert FAKE_CODE not in str(error.value)
    assert stream.closed


async def test_exchange_preserves_valid_token_whitespace():
    result = await make_client(
        lambda request: json_response({"access_token": " token-with-space "})
    ).exchange_authorization_code(FAKE_CODE)
    assert result.access_token.get_secret_value() == " token-with-space "


async def test_exchange_sets_trust_env_false(monkeypatch):
    observed = {}
    original_client = httpx.AsyncClient

    def capturing_client(*args, **kwargs):
        observed.update(kwargs)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(
        "app.integrations.whatsapp.embedded_signup_exchange.httpx.AsyncClient",
        capturing_client,
    )
    await make_client(
        lambda request: json_response({"access_token": FAKE_TOKEN})
    ).exchange_authorization_code(FAKE_CODE)
    assert observed["trust_env"] is False


async def test_exchange_errors_and_result_do_not_reveal_sensitive_values(caplog):
    with pytest.raises(MetaEmbeddedSignupExchangeResponseError) as error:
        await make_client(lambda request: json_response({})).exchange_authorization_code(
            FAKE_CODE
        )
    rendered = f"{error.value!r} {error.value}"
    assert FAKE_CODE not in rendered
    assert FAKE_SECRET not in rendered
    assert FAKE_TOKEN not in rendered
    assert FAKE_CODE not in caplog.text
    assert FAKE_SECRET not in caplog.text
    assert FAKE_TOKEN not in caplog.text
