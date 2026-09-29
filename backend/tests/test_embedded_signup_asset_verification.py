import json

import httpx
import pytest
from pydantic import SecretStr

from app.integrations.whatsapp.embedded_signup_asset_verification import (
    MetaEmbeddedSignupAssetMembershipMismatchError,
    MetaEmbeddedSignupAssetPaginationIncompleteError,
    MetaEmbeddedSignupAssetVerificationContentEncodingError,
    MetaEmbeddedSignupAssetVerificationInputError,
    MetaEmbeddedSignupAssetVerificationJSONError,
    MetaEmbeddedSignupAssetVerificationResponseTooLargeError,
    MetaEmbeddedSignupAssetVerificationSchemaError,
    MetaEmbeddedSignupAssetVerificationTimeoutError,
    MetaEmbeddedSignupAssetVerificationTransportError,
    MetaEmbeddedSignupAssetVerificationUpstreamError,
    MetaEmbeddedSignupAssetVerifier,
)


FAKE_CUSTOMER_TOKEN = "test-customer-embedded-signup-token-not-real"
FAKE_WABA_ID = "123456789012345"
FAKE_PHONE_ID = "987654321098765"
OTHER_PHONE_ID = "111111111111111"


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


def make_verifier(handler, *, maximum_bytes=16_384):
    return MetaEmbeddedSignupAssetVerifier(
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


def phone_data(*phone_ids, paging=None):
    result = {"data": [{"id": phone_id} for phone_id in phone_ids]}
    if paging is not None:
        result["paging"] = paging
    return result


async def test_verifier_constructs_exact_customer_token_request_once():
    requests = []

    def handler(request):
        requests.append(request)
        return response(phone_data(FAKE_PHONE_ID))

    result = await make_verifier(handler).verify_phone_membership(
        SecretStr(FAKE_CUSTOMER_TOKEN),
        FAKE_WABA_ID,
        FAKE_PHONE_ID,
    )

    assert result.waba_id == FAKE_WABA_ID
    assert result.phone_number_id == FAKE_PHONE_ID
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == (
        f"https://graph.facebook.com/v25.0/{FAKE_WABA_ID}/phone_numbers"
    )
    assert request.url.query == b""
    assert request.headers["authorization"] == f"Bearer {FAKE_CUSTOMER_TOKEN}"
    assert request.headers["accept-encoding"] == "identity"


@pytest.mark.parametrize(
    "candidate_id",
    [
        "",
        " ",
        "+123",
        "-123",
        "123.0",
        "1e3",
        "123/phone_numbers",
        "123?x=1",
        "123#fragment",
        "../123",
        "1" * 65,
        123,
        True,
        None,
    ],
)
async def test_verifier_rejects_untrusted_candidate_ids_before_transport(candidate_id):
    calls = []

    def handler(request):
        calls.append(request)
        return response(phone_data(FAKE_PHONE_ID))

    with pytest.raises(MetaEmbeddedSignupAssetVerificationInputError):
        await make_verifier(handler).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            candidate_id,
            FAKE_PHONE_ID,
        )
    assert calls == []


async def test_verifier_rejects_invalid_phone_candidate_before_transport():
    calls = []

    def handler(request):
        calls.append(request)
        return response(phone_data(FAKE_PHONE_ID))

    with pytest.raises(MetaEmbeddedSignupAssetVerificationInputError):
        await make_verifier(handler).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            " 987654321098765",
        )
    assert calls == []


async def test_verifier_requires_exact_phone_membership():
    with pytest.raises(MetaEmbeddedSignupAssetMembershipMismatchError):
        await make_verifier(
            lambda request: response(phone_data(OTHER_PHONE_ID))
        ).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )


async def test_verifier_returns_mismatch_only_when_paging_is_absent():
    with pytest.raises(MetaEmbeddedSignupAssetMembershipMismatchError):
        await make_verifier(
            lambda request: response(phone_data(OTHER_PHONE_ID))
        ).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )


async def test_verifier_treats_empty_paging_object_as_terminal():
    with pytest.raises(MetaEmbeddedSignupAssetMembershipMismatchError):
        await make_verifier(
            lambda request: response(phone_data(OTHER_PHONE_ID, paging={}))
        ).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )


async def test_verifier_accepts_numeric_response_id_only_when_exactly_equal():
    result = await make_verifier(
        lambda request: response(phone_data(int(FAKE_PHONE_ID)))
    ).verify_phone_membership(
        FAKE_CUSTOMER_TOKEN,
        FAKE_WABA_ID,
        FAKE_PHONE_ID,
    )
    assert result.phone_number_id == FAKE_PHONE_ID


@pytest.mark.parametrize(
    "bad_id",
    [True, 1.0, None, "not-numeric", " 987654321098765"],
)
async def test_verifier_rejects_invalid_response_phone_ids(bad_id):
    with pytest.raises(MetaEmbeddedSignupAssetVerificationSchemaError):
        await make_verifier(lambda request: response(phone_data(bad_id))).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )


@pytest.mark.parametrize(
    "payload",
    [{}, {"data": {}}, {"data": ["not-an-object"]}],
)
async def test_verifier_rejects_malformed_top_level_or_entries(payload):
    with pytest.raises(MetaEmbeddedSignupAssetVerificationSchemaError):
        await make_verifier(lambda request: response(payload)).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )


async def test_verifier_rejects_malformed_json():
    with pytest.raises(MetaEmbeddedSignupAssetVerificationJSONError):
        await make_verifier(
            lambda request: response({}, stream=ControlledAsyncByteStream([b"not-json"]))
        ).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )


@pytest.mark.parametrize(
    "paging",
    [
        None,
        {"next": None},
        {"next": ""},
        {"next": 123},
        {"cursors": None},
        {"cursors": []},
        {"cursors": {"after": None}},
        {"cursors": {"after": ""}},
        {"cursors": {"after": 123}},
    ],
)
async def test_verifier_rejects_ambiguous_or_malformed_pagination(paging):
    with pytest.raises(MetaEmbeddedSignupAssetVerificationSchemaError):
        await make_verifier(
            lambda request: response({"data": [{"id": OTHER_PHONE_ID}], "paging": paging})
        ).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )


async def test_verifier_does_not_claim_absence_when_next_page_exists():
    with pytest.raises(MetaEmbeddedSignupAssetPaginationIncompleteError):
        await make_verifier(
            lambda request: response(
                phone_data(OTHER_PHONE_ID, paging={"next": "opaque-next-page"})
            )
        ).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )


async def test_verifier_never_follows_next_url():
    requests = []

    def handler(request):
        requests.append(request)
        return response(
            phone_data(OTHER_PHONE_ID, paging={"next": "https://foreign.test/next"})
        )

    with pytest.raises(MetaEmbeddedSignupAssetPaginationIncompleteError):
        await make_verifier(handler).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )
    assert len(requests) == 1


async def test_verifier_treats_after_cursor_as_incomplete_without_following_it():
    requests = []

    def handler(request):
        requests.append(request)
        return response(phone_data(OTHER_PHONE_ID, paging={"cursors": {"after": "opaque"}}))

    with pytest.raises(MetaEmbeddedSignupAssetPaginationIncompleteError):
        await make_verifier(handler).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )
    assert len(requests) == 1


async def test_verifier_allows_membership_found_on_first_page_even_if_more_pages_exist():
    result = await make_verifier(
        lambda request: response(
            phone_data(FAKE_PHONE_ID, paging={"next": "opaque-next-page"})
        )
    ).verify_phone_membership(
        FAKE_CUSTOMER_TOKEN,
        FAKE_WABA_ID,
        FAKE_PHONE_ID,
    )
    assert result.phone_number_id == FAKE_PHONE_ID


@pytest.mark.parametrize(
    "phone_ids",
    [
        (FAKE_PHONE_ID, None),
        (None, FAKE_PHONE_ID),
    ],
)
async def test_verifier_validates_full_page_before_declaring_membership(phone_ids):
    entries = [
        {"id": phone_id} if phone_id is not None else {"id": None}
        for phone_id in phone_ids
    ]
    with pytest.raises(MetaEmbeddedSignupAssetVerificationSchemaError):
        await make_verifier(lambda request: response({"data": entries})).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )


@pytest.mark.parametrize("status", [403, 429, 500])
async def test_verifier_sanitizes_http_rejection_without_retry(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, content=b'{"error":"provider-secret"}')

    with pytest.raises(MetaEmbeddedSignupAssetVerificationUpstreamError) as error:
        await make_verifier(handler).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )
    assert error.value.status_code == status
    assert len(calls) == 1
    assert "provider-secret" not in str(error.value)
    assert FAKE_CUSTOMER_TOKEN not in str(error.value)


async def test_verifier_sanitizes_timeout_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("provider-secret", request=request)

    with pytest.raises(MetaEmbeddedSignupAssetVerificationTimeoutError) as error:
        await make_verifier(handler).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )
    assert len(calls) == 1
    assert FAKE_CUSTOMER_TOKEN not in str(error.value)


async def test_verifier_sanitizes_transport_error_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("provider-secret", request=request)

    with pytest.raises(MetaEmbeddedSignupAssetVerificationTransportError) as error:
        await make_verifier(handler).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )
    assert len(calls) == 1
    assert FAKE_CUSTOMER_TOKEN not in str(error.value)


async def test_verifier_rejects_oversized_response_without_consuming_remainder():
    body = json.dumps(phone_data(FAKE_PHONE_ID)).encode()
    stream = ControlledAsyncByteStream([body[:8], body[8:], b"must-not-be-read"])
    with pytest.raises(MetaEmbeddedSignupAssetVerificationResponseTooLargeError):
        await make_verifier(
            lambda request: response({}, stream=stream),
            maximum_bytes=len(body) - 1,
        ).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )
    assert stream.read_count == 2
    assert stream.closed


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "unknown"])
async def test_verifier_rejects_compressed_or_unknown_content_encoding(encoding):
    stream = ControlledAsyncByteStream([b"must-not-be-read"])
    with pytest.raises(MetaEmbeddedSignupAssetVerificationContentEncodingError):
        await make_verifier(
            lambda request: response(
                {},
                headers={"content-encoding": encoding},
                stream=stream,
            )
        ).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )
    assert stream.read_count == 0
    assert stream.closed


async def test_verifier_does_not_follow_redirects_or_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://example.test/elsewhere"})

    with pytest.raises(MetaEmbeddedSignupAssetVerificationUpstreamError):
        await make_verifier(handler).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )
    assert len(calls) == 1


async def test_verifier_sanitizes_stream_request_error():
    stream = ControlledAsyncByteStream(error=httpx.DecodingError("provider-secret"))
    with pytest.raises(MetaEmbeddedSignupAssetVerificationTransportError) as error:
        await make_verifier(
            lambda request: response({}, stream=stream)
        ).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )
    assert stream.closed
    assert FAKE_CUSTOMER_TOKEN not in str(error.value)


async def test_verifier_result_errors_and_logs_do_not_reveal_customer_token(caplog):
    with pytest.raises(MetaEmbeddedSignupAssetMembershipMismatchError) as error:
        await make_verifier(
            lambda request: response(phone_data(OTHER_PHONE_ID))
        ).verify_phone_membership(
            FAKE_CUSTOMER_TOKEN,
            FAKE_WABA_ID,
            FAKE_PHONE_ID,
        )
    rendered = f"{error.value!r} {error.value}"
    assert FAKE_CUSTOMER_TOKEN not in rendered
    assert FAKE_CUSTOMER_TOKEN not in caplog.text


async def test_verifier_sets_trust_env_false(monkeypatch):
    observed = {}
    original_client = httpx.AsyncClient

    def capturing_client(*args, **kwargs):
        observed.update(kwargs)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(
        "app.integrations.whatsapp.embedded_signup_asset_verification.httpx.AsyncClient",
        capturing_client,
    )
    await make_verifier(lambda request: response(phone_data(FAKE_PHONE_ID))).verify_phone_membership(
        FAKE_CUSTOMER_TOKEN,
        FAKE_WABA_ID,
        FAKE_PHONE_ID,
    )
    assert observed["trust_env"] is False
