import json

import httpx
import pytest
from pydantic import SecretStr

from app.integrations.whatsapp.embedded_signup_subscription import (
    EmbeddedSignupSubscriptionOutcome,
    MetaEmbeddedSignupSubscriptionInputError,
    MetaEmbeddedSignupSubscriptionManager,
)


PROVIDER_BUSINESS_ID = "100000000000001"
APP_ID = "200000000000002"
WABA_ID = "300000000000003"
OTHER_ID = "400000000000004"
PROVIDER_TOKEN = "test-provider-system-user-token-not-real"


class ControlledAsyncByteStream(httpx.AsyncByteStream):
    def __init__(self, chunks, *, error=None):
        self._chunks = chunks
        self._error = error

    async def __aiter__(self):
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error

    async def aclose(self):
        return None


def manager(handler, *, maximum_bytes=16_384):
    return MetaEmbeddedSignupSubscriptionManager(
        provider_business_id=PROVIDER_BUSINESS_ID,
        app_id=APP_ID,
        provider_system_user_token=SecretStr(PROVIDER_TOKEN),
        graph_version="v25.0",
        max_response_bytes=maximum_bytes,
        transport=httpx.MockTransport(handler),
    )


def response(payload, *, status=200, headers=None, stream_error=None):
    actual_headers = {"content-type": "application/json"}
    if headers:
        actual_headers.update(headers)
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return httpx.Response(
        status,
        headers=actual_headers,
        stream=ControlledAsyncByteStream([content], error=stream_error),
    )


def shared(*ids, paging=None):
    body = {"data": [{"id": value} for value in ids]}
    if paging is not None:
        body["paging"] = paging
    return body


def subscriptions(*ids, paging=None):
    body = {"data": [{"whatsapp_business_api_data": {"id": value}} for value in ids]}
    if paging is not None:
        body["paging"] = paging
    return body


async def test_uses_only_provider_token_and_exact_preflight_paths():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("client_whatsapp_business_accounts"):
            return response(shared(WABA_ID))
        return response(subscriptions(APP_ID))

    result = await manager(handler).ensure_app_subscribed(WABA_ID)

    assert result.outcome is EmbeddedSignupSubscriptionOutcome.ALREADY_SUBSCRIBED
    assert [request.method for request in calls] == ["GET", "GET"]
    assert str(calls[0].url) == (
        "https://graph.facebook.com/v25.0/"
        f"{PROVIDER_BUSINESS_ID}/client_whatsapp_business_accounts"
    )
    assert str(calls[1].url) == f"https://graph.facebook.com/v25.0/{WABA_ID}/subscribed_apps"
    assert all(request.headers["authorization"] == f"Bearer {PROVIDER_TOKEN}" for request in calls)
    assert all(request.headers["accept-encoding"] == "identity" for request in calls)


@pytest.mark.parametrize("candidate", ["", " 1", "1 ", 1, True, None, "1" * 65])
async def test_rejects_untrusted_candidate_before_any_request(candidate):
    calls = []
    with pytest.raises(MetaEmbeddedSignupSubscriptionInputError):
        await manager(lambda request: calls.append(request)).ensure_app_subscribed(candidate)
    assert calls == []


async def test_shared_waba_absent_terminal_never_reads_or_posts_subscriptions():
    calls = []
    result = await manager(lambda request: (calls.append(request), response(shared(OTHER_ID)))[1]).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.WABA_NOT_SHARED
    assert len(calls) == 1


async def test_shared_waba_absent_non_terminal_never_follows_next_or_posts():
    calls = []
    result = await manager(
        lambda request: (calls.append(request), response(shared(OTHER_ID, paging={"next": "opaque"})))[1]
    ).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.AUTHORITY_PAGINATION_INCOMPLETE
    assert len(calls) == 1


@pytest.mark.parametrize("bad_id", [True, 1.1, None, " 300000000000003"])
async def test_shared_preflight_validates_every_entry(bad_id):
    result = await manager(lambda request: response(shared(WABA_ID, bad_id))).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.AUTHORITY_INVALID_SCHEMA


async def test_subscribed_app_absent_non_terminal_never_posts():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("client_whatsapp_business_accounts"):
            return response(shared(WABA_ID))
        return response(subscriptions(OTHER_ID, paging={"cursors": {"after": "opaque"}}))

    result = await manager(handler).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.SUBSCRIPTION_PAGINATION_INCOMPLETE
    assert [request.method for request in calls] == ["GET", "GET"]


@pytest.mark.parametrize("bad_id", [True, 1.0, None, " 200000000000002"])
async def test_subscriptions_validates_all_entries_even_after_app_match(bad_id):
    def handler(request):
        if request.url.path.endswith("client_whatsapp_business_accounts"):
            return response(shared(WABA_ID))
        return response(subscriptions(APP_ID, bad_id))

    result = await manager(handler).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.AUTHORITY_INVALID_SCHEMA


async def test_authority_rejection_and_transport_never_post():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("client_whatsapp_business_accounts"):
            return response(shared(WABA_ID))
        return response({}, status=403)

    result = await manager(handler).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.AUTHORITY_UPSTREAM_REJECTED
    assert [request.method for request in calls] == ["GET", "GET"]


@pytest.mark.parametrize(
    "headers",
    [
        {"content-encoding": "gzip"},
        {"content-type": "text/plain"},
    ],
)
async def test_unsafe_shared_response_never_reaches_subscription(headers):
    calls = []
    result = await manager(
        lambda request: (calls.append(request), response(shared(WABA_ID), headers=headers))[1]
    ).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.AUTHORITY_INVALID_SCHEMA
    assert len(calls) == 1


async def test_oversized_shared_response_never_reaches_subscription():
    calls = []
    result = await manager(
        lambda request: (calls.append(request), response(shared(WABA_ID), headers={"content-length": "100"}))[1],
        maximum_bytes=99,
    ).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.AUTHORITY_INVALID_SCHEMA
    assert len(calls) == 1


@pytest.mark.parametrize("ack", [{"success": True}, {"success": "true"}])
async def test_post_documented_success_is_verified_by_get(ack):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("client_whatsapp_business_accounts"):
            return response(shared(WABA_ID))
        subscribed_gets = [call for call in calls if call.method == "GET" and call.url.path.endswith("subscribed_apps")]
        if request.method == "POST":
            return response(ack)
        return response(subscriptions(OTHER_ID if len(subscribed_gets) == 1 else APP_ID))

    result = await manager(handler).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.SUBSCRIBED_AND_VERIFIED
    assert [request.method for request in calls] == ["GET", "GET", "POST", "GET"]


@pytest.mark.parametrize(
    "ack",
    [
        {},
        {"success": None},
        {"success": 1},
        {"success": 0},
        {"success": False},
        {"success": "false"},
        {"success": []},
        {"success": {}},
        {"success": "TRUE"},
        {"success": " true "},
    ],
)
async def test_invalid_ack_is_reconciled_without_second_post(ack):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("client_whatsapp_business_accounts"):
            return response(shared(WABA_ID))
        if request.method == "POST":
            return response(ack)
        return response(subscriptions(APP_ID if len(calls) == 4 else OTHER_ID))

    result = await manager(handler).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.RECONCILIATION_CONFIRMED
    assert [request.method for request in calls].count("POST") == 1
    assert [request.method for request in calls] == ["GET", "GET", "POST", "GET"]


async def test_post_rejection_is_not_replayed():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("client_whatsapp_business_accounts"):
            return response(shared(WABA_ID))
        if request.method == "POST":
            return response({}, status=500)
        return response(subscriptions(OTHER_ID))

    result = await manager(handler).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.POST_REJECTED
    assert [request.method for request in calls] == ["GET", "GET", "POST"]


@pytest.mark.parametrize(
    ("reconciliation_payload", "expected"),
    [
        (subscriptions(APP_ID), EmbeddedSignupSubscriptionOutcome.RECONCILIATION_CONFIRMED),
        (subscriptions(OTHER_ID), EmbeddedSignupSubscriptionOutcome.RECONCILIATION_INCOMPLETE),
    ],
)
async def test_ambiguous_post_is_reconciled_once_without_replay(reconciliation_payload, expected):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("client_whatsapp_business_accounts"):
            return response(shared(WABA_ID))
        if request.method == "POST":
            raise httpx.ReadError("synthetic", request=request)
        return response(subscriptions(OTHER_ID if len(calls) == 2 else reconciliation_payload["data"][0]["whatsapp_business_api_data"]["id"]))

    result = await manager(handler).ensure_app_subscribed(WABA_ID)
    assert result.outcome is expected
    assert [request.method for request in calls] == ["GET", "GET", "POST", "GET"]


async def test_post_success_but_final_absence_is_not_success_and_never_reposts():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("client_whatsapp_business_accounts"):
            return response(shared(WABA_ID))
        if request.method == "POST":
            return response({"success": True})
        return response(subscriptions(OTHER_ID))

    result = await manager(handler).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.VERIFICATION_INCOMPLETE
    assert [request.method for request in calls].count("POST") == 1


@pytest.mark.parametrize(
    ("post_response", "maximum_bytes"),
    [
        (lambda: response(b"not-json"), 16_384),
        (lambda: response({}, headers={"content-type": "text/plain"}), 16_384),
        (lambda: response({}, headers={"content-encoding": "gzip"}), 16_384),
        (lambda: response({}, headers={"content-length": "100"}), 99),
    ],
)
async def test_ambiguous_post_response_is_reconciled_once(post_response, maximum_bytes):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("client_whatsapp_business_accounts"):
            return response(shared(WABA_ID))
        if request.method == "POST":
            return post_response()
        return response(subscriptions(APP_ID if len(calls) == 4 else OTHER_ID))

    subscription_manager = manager(handler, maximum_bytes=maximum_bytes)
    result = await subscription_manager.ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.RECONCILIATION_CONFIRMED
    assert [request.method for request in calls] == ["GET", "GET", "POST", "GET"]


@pytest.mark.parametrize(
    ("reconciliation_id", "expected"),
    [
        (APP_ID, EmbeddedSignupSubscriptionOutcome.RECONCILIATION_CONFIRMED),
        (OTHER_ID, EmbeddedSignupSubscriptionOutcome.RECONCILIATION_INCOMPLETE),
    ],
)
async def test_stream_error_after_post_is_reconciled_once(reconciliation_id, expected):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("client_whatsapp_business_accounts"):
            return response(shared(WABA_ID))
        if request.method == "POST":
            return response({}, stream_error=httpx.StreamError("synthetic"))
        return response(subscriptions(OTHER_ID if len(calls) == 2 else reconciliation_id))

    result = await manager(handler).ensure_app_subscribed(WABA_ID)
    assert result.outcome is expected
    assert [request.method for request in calls] == ["GET", "GET", "POST", "GET"]
    assert [request.method for request in calls].count("POST") == 1


async def test_preflight_transport_failure_never_posts_or_reconciles():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadError("synthetic", request=request)

    result = await manager(handler).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.AUTHORITY_TRANSPORT_ERROR
    assert [request.method for request in calls] == ["GET"]


@pytest.mark.parametrize("paging", [{"next": " "}, {"cursors": {"after": " "}}])
async def test_whitespace_pagination_remains_conservatively_incomplete(paging):
    result = await manager(
        lambda request: response(shared(OTHER_ID, paging=paging))
    ).ensure_app_subscribed(WABA_ID)
    assert result.outcome is EmbeddedSignupSubscriptionOutcome.AUTHORITY_PAGINATION_INCOMPLETE
