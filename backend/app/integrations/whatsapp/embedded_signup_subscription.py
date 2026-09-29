"""Provider-side, one-shot WABA webhook subscription for Embedded Signup.

This module deliberately has no database or onboarding-attempt dependency.  It
only establishes provider authority and makes at most one remote mutation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

import httpx
from pydantic import SecretStr

from app.integrations.whatsapp.meta_graph_response import (
    MetaGraphResponseTooLargeError,
    is_identity_content_encoding,
    is_json_content_type,
    read_bounded_raw_response,
)


_GRAPH_HOST = "https://graph.facebook.com"
_VERSION_PATTERN = re.compile(r"v\d+\.\d+")
_META_ID_PATTERN = re.compile(r"[0-9]{1,64}")


class EmbeddedSignupSubscriptionOutcome(StrEnum):
    ALREADY_SUBSCRIBED = "already_subscribed"
    SUBSCRIBED_AND_VERIFIED = "subscribed_and_verified"
    RECONCILIATION_CONFIRMED = "reconciliation_confirmed"
    WABA_NOT_SHARED = "waba_not_shared"
    AUTHORITY_PAGINATION_INCOMPLETE = "authority_pagination_incomplete"
    AUTHORITY_UPSTREAM_REJECTED = "authority_upstream_rejected"
    AUTHORITY_TRANSPORT_ERROR = "authority_transport_error"
    AUTHORITY_INVALID_SCHEMA = "authority_invalid_schema"
    SUBSCRIPTION_PAGINATION_INCOMPLETE = "subscription_pagination_incomplete"
    POST_REJECTED = "post_rejected"
    POST_RESPONSE_INVALID = "post_response_invalid"
    VERIFICATION_INCOMPLETE = "verification_incomplete"
    RECONCILIATION_INCOMPLETE = "reconciliation_incomplete"


@dataclass(frozen=True)
class EmbeddedSignupSubscriptionResult:
    outcome: EmbeddedSignupSubscriptionOutcome


class MetaEmbeddedSignupSubscriptionConfigurationError(Exception):
    """Sanitized configuration error; never include provider credentials."""


class MetaEmbeddedSignupSubscriptionInputError(Exception):
    """Sanitized invalid candidate WABA error."""


class MetaEmbeddedSignupSubscriptionManager:
    """Establish provider authority and subscribe the configured app once."""

    def __init__(
        self,
        *,
        provider_business_id: str,
        app_id: str,
        provider_system_user_token: SecretStr,
        graph_version: str,
        max_response_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        _validate_config_id(provider_business_id)
        _validate_config_id(app_id)
        if not provider_system_user_token.get_secret_value():
            raise MetaEmbeddedSignupSubscriptionConfigurationError(
                "Meta Embedded Signup subscription is not configured"
            )
        if not _VERSION_PATTERN.fullmatch(graph_version) or max_response_bytes <= 0:
            raise MetaEmbeddedSignupSubscriptionConfigurationError(
                "Meta Embedded Signup subscription configuration is invalid"
            )
        self._provider_business_id = provider_business_id
        self._app_id = app_id
        self._provider_system_user_token = provider_system_user_token
        self._graph_version = graph_version
        self._max_response_bytes = max_response_bytes
        self._transport = transport

    def _url(self, path: str) -> str:
        return f"{_GRAPH_HOST}/{self._graph_version}/{path}"

    async def ensure_app_subscribed(
        self, candidate_waba_id: str
    ) -> EmbeddedSignupSubscriptionResult:
        _validate_candidate_id(candidate_waba_id)
        async with self._client() as client:
            shared = await self._get_json(
                client,
                self._url(
                    f"{self._provider_business_id}/client_whatsapp_business_accounts"
                ),
            )
            shared_result = _membership_result(
                shared, candidate_waba_id, entry_id_path=("id",)
            )
            if shared_result == "absent":
                return _result(EmbeddedSignupSubscriptionOutcome.WABA_NOT_SHARED)
            if shared_result == "incomplete":
                return _result(
                    EmbeddedSignupSubscriptionOutcome.AUTHORITY_PAGINATION_INCOMPLETE
                )
            if shared_result == "invalid":
                return _result(EmbeddedSignupSubscriptionOutcome.AUTHORITY_INVALID_SCHEMA)
            if shared_result == "rejected":
                return _result(EmbeddedSignupSubscriptionOutcome.AUTHORITY_UPSTREAM_REJECTED)
            if shared_result != "found":
                return _result(EmbeddedSignupSubscriptionOutcome.AUTHORITY_TRANSPORT_ERROR)

            subscribed = await self._get_json(
                client, self._url(f"{candidate_waba_id}/subscribed_apps")
            )
            subscription_result = _membership_result(
                subscribed,
                self._app_id,
                entry_id_path=("whatsapp_business_api_data", "id"),
            )
            if subscription_result == "found":
                return _result(EmbeddedSignupSubscriptionOutcome.ALREADY_SUBSCRIBED)
            if subscription_result == "incomplete":
                return _result(
                    EmbeddedSignupSubscriptionOutcome.SUBSCRIPTION_PAGINATION_INCOMPLETE
                )
            if subscription_result == "invalid":
                return _result(EmbeddedSignupSubscriptionOutcome.AUTHORITY_INVALID_SCHEMA)
            if subscription_result == "rejected":
                return _result(EmbeddedSignupSubscriptionOutcome.AUTHORITY_UPSTREAM_REJECTED)
            if subscription_result != "absent":
                return _result(EmbeddedSignupSubscriptionOutcome.AUTHORITY_TRANSPORT_ERROR)

            post = await self._post_json(
                client, self._url(f"{candidate_waba_id}/subscribed_apps")
            )
            if post == "rejected":
                return _result(EmbeddedSignupSubscriptionOutcome.POST_REJECTED)
            if post == "success":
                verification = await self._get_json(
                    client, self._url(f"{candidate_waba_id}/subscribed_apps")
                )
                return _verified_or_incomplete(
                    verification,
                    self._app_id,
                    success=EmbeddedSignupSubscriptionOutcome.SUBSCRIBED_AND_VERIFIED,
                    incomplete=EmbeddedSignupSubscriptionOutcome.VERIFICATION_INCOMPLETE,
                )

            # Every non-clear HTTP-success acknowledgement is ambiguous after
            # the mutation attempt. Reconciliation never emits another POST.
            return await self._reconcile_subscription(client, candidate_waba_id)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=10.0),
            follow_redirects=False,
            trust_env=False,
        )

    async def _get_json(self, client: httpx.AsyncClient, url: str) -> object | str:
        return await self._request_json(client, "GET", url)

    async def _post_json(self, client: httpx.AsyncClient, url: str) -> str:
        response = await self._request_json(client, "POST", url)
        if response == "rejected":
            return "rejected"
        if response == "transport" or response == "invalid":
            return "ambiguous"
        if not isinstance(response, dict):
            return "ambiguous"
        success = response.get("success")
        if success is True or success == "true":
            return "success"
        return "ambiguous"

    async def _reconcile_subscription(
        self, client: httpx.AsyncClient, candidate_waba_id: str
    ) -> EmbeddedSignupSubscriptionResult:
        reconciliation = await self._get_json(
            client, self._url(f"{candidate_waba_id}/subscribed_apps")
        )
        return _verified_or_incomplete(
            reconciliation,
            self._app_id,
            success=EmbeddedSignupSubscriptionOutcome.RECONCILIATION_CONFIRMED,
            incomplete=EmbeddedSignupSubscriptionOutcome.RECONCILIATION_INCOMPLETE,
        )

    async def _request_json(
        self, client: httpx.AsyncClient, method: str, url: str
    ) -> object | str:
        try:
            async with client.stream(
                method,
                url,
                headers={
                    "Authorization": (
                        "Bearer "
                        f"{self._provider_system_user_token.get_secret_value()}"
                    ),
                    "Accept-Encoding": "identity",
                },
            ) as response:
                if response.status_code != httpx.codes.OK:
                    return "rejected"
                if not is_json_content_type(response.headers.get("content-type")):
                    return "invalid"
                if not is_identity_content_encoding(response.headers.get("content-encoding")):
                    return "invalid"
                try:
                    body = await read_bounded_raw_response(response, self._max_response_bytes)
                except MetaGraphResponseTooLargeError:
                    return "invalid"
        # StreamError is deliberately separate from RequestError in httpx.
        # It can occur after a POST reached Meta, so callers must reconcile.
        except (httpx.TimeoutException, httpx.RequestError, httpx.StreamError):
            return "transport"
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return "invalid"
        return decoded if isinstance(decoded, dict) else "invalid"


def _result(outcome: EmbeddedSignupSubscriptionOutcome) -> EmbeddedSignupSubscriptionResult:
    return EmbeddedSignupSubscriptionResult(outcome)


def _verified_or_incomplete(
    response: object | str,
    app_id: str,
    *,
    success: EmbeddedSignupSubscriptionOutcome,
    incomplete: EmbeddedSignupSubscriptionOutcome,
) -> EmbeddedSignupSubscriptionResult:
    return _result(success if _membership_result(response, app_id, entry_id_path=("whatsapp_business_api_data", "id")) == "found" else incomplete)


def _membership_result(
    response: object | str, target_id: str, *, entry_id_path: tuple[str, ...]
) -> str:
    if response == "rejected":
        return "rejected"
    if response == "transport":
        return "transport"
    if response == "invalid" or not isinstance(response, dict):
        return "invalid"
    data = response.get("data")
    if not isinstance(data, list):
        return "invalid"
    found = False
    for entry in data:
        if not isinstance(entry, dict):
            return "invalid"
        value: object = entry
        for key in entry_id_path:
            if not isinstance(value, dict) or key not in value:
                return "invalid"
            value = value[key]
        try:
            parsed = _parse_response_id(value)
        except ValueError:
            return "invalid"
        found = found or parsed == target_id
    if found:
        return "found"
    try:
        return "incomplete" if _has_next_page(response) else "absent"
    except ValueError:
        return "invalid"


def _validate_candidate_id(value: object) -> None:
    if not isinstance(value, str) or not _META_ID_PATTERN.fullmatch(value):
        raise MetaEmbeddedSignupSubscriptionInputError(
            "Meta Embedded Signup candidate WABA ID is invalid"
        )


def _validate_config_id(value: object) -> None:
    if not isinstance(value, str) or not _META_ID_PATTERN.fullmatch(value):
        raise MetaEmbeddedSignupSubscriptionConfigurationError(
            "Meta Embedded Signup subscription identifier is invalid"
        )


def _parse_response_id(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError
    parsed = str(value)
    if not _META_ID_PATTERN.fullmatch(parsed):
        raise ValueError
    return parsed


def _has_next_page(response: dict[str, object]) -> bool:
    if "paging" not in response:
        return False
    paging = response["paging"]
    if not isinstance(paging, dict):
        raise ValueError
    if "next" in paging:
        if not isinstance(paging["next"], str) or not paging["next"]:
            raise ValueError
        return True
    if "cursors" in paging:
        cursors = paging["cursors"]
        if not isinstance(cursors, dict):
            raise ValueError
        if "after" in cursors:
            if not isinstance(cursors["after"], str) or not cursors["after"]:
                raise ValueError
            return True
    return False
