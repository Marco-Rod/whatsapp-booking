"""One-shot WABA-to-phone membership verification for Embedded Signup."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

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


class MetaEmbeddedSignupAssetVerificationError(Exception):
    """Sanitized verification failure; never include tokens or raw responses."""


class MetaEmbeddedSignupAssetVerificationConfigurationError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "configuration"


class MetaEmbeddedSignupAssetVerificationInputError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "invalid_input"


class MetaEmbeddedSignupAssetVerificationTransportError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "transport"


class MetaEmbeddedSignupAssetVerificationTimeoutError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "timeout"


class MetaEmbeddedSignupAssetVerificationUpstreamError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "upstream"

    def __init__(self, status_code: int) -> None:
        super().__init__("Meta Embedded Signup asset verification was rejected")
        self.status_code = status_code


class MetaEmbeddedSignupAssetVerificationResponseTooLargeError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "response_too_large"


class MetaEmbeddedSignupAssetVerificationContentTypeError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "invalid_content_type"


class MetaEmbeddedSignupAssetVerificationContentEncodingError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "invalid_content_encoding"


class MetaEmbeddedSignupAssetVerificationJSONError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "invalid_json"


class MetaEmbeddedSignupAssetVerificationSchemaError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "invalid_schema"


class MetaEmbeddedSignupAssetMembershipMismatchError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "membership_mismatch"


class MetaEmbeddedSignupAssetPaginationIncompleteError(
    MetaEmbeddedSignupAssetVerificationError
):
    category = "pagination_incomplete"


@dataclass(frozen=True)
class VerifiedEmbeddedSignupAssets:
    waba_id: str
    phone_number_id: str


class MetaEmbeddedSignupAssetVerifier:
    """Verify one candidate WABA page using exactly one customer-token request."""

    def __init__(
        self,
        *,
        graph_version: str,
        max_response_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not _VERSION_PATTERN.fullmatch(graph_version):
            raise MetaEmbeddedSignupAssetVerificationConfigurationError(
                "Meta Embedded Signup asset verification version is invalid"
            )
        if max_response_bytes <= 0:
            raise MetaEmbeddedSignupAssetVerificationConfigurationError(
                "Meta Embedded Signup asset verification response limit is invalid"
            )
        self._graph_version = graph_version
        self._max_response_bytes = max_response_bytes
        self._transport = transport

    def _phone_numbers_url(self, candidate_waba_id: str) -> str:
        return f"{_GRAPH_HOST}/{self._graph_version}/{candidate_waba_id}/phone_numbers"

    async def verify_phone_membership(
        self,
        access_token: SecretStr | str,
        candidate_waba_id: str,
        candidate_phone_number_id: str,
    ) -> VerifiedEmbeddedSignupAssets:
        token = (
            access_token.get_secret_value()
            if isinstance(access_token, SecretStr)
            else access_token
        )
        if not isinstance(token, str) or not token.strip():
            raise MetaEmbeddedSignupAssetVerificationInputError(
                "Meta Embedded Signup asset verification token is invalid"
            )
        _validate_candidate_id(candidate_waba_id)
        _validate_candidate_id(candidate_phone_number_id)

        timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=10.0)
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "GET",
                    self._phone_numbers_url(candidate_waba_id),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    if response.status_code != httpx.codes.OK:
                        raise MetaEmbeddedSignupAssetVerificationUpstreamError(
                            response.status_code
                        )
                    if not is_json_content_type(response.headers.get("content-type")):
                        raise MetaEmbeddedSignupAssetVerificationContentTypeError(
                            "Meta Embedded Signup asset verification response is not JSON"
                        )
                    if not is_identity_content_encoding(
                        response.headers.get("content-encoding")
                    ):
                        raise MetaEmbeddedSignupAssetVerificationContentEncodingError(
                            "Meta Embedded Signup asset verification response encoding is unsupported"
                        )
                    try:
                        body = await read_bounded_raw_response(
                            response,
                            self._max_response_bytes,
                        )
                    except MetaGraphResponseTooLargeError:
                        raise MetaEmbeddedSignupAssetVerificationResponseTooLargeError(
                            "Meta Embedded Signup asset verification response is too large"
                        ) from None
        except MetaEmbeddedSignupAssetVerificationError:
            raise
        except httpx.TimeoutException:
            raise MetaEmbeddedSignupAssetVerificationTimeoutError(
                "Meta Embedded Signup asset verification timed out"
            ) from None
        except httpx.RequestError:
            raise MetaEmbeddedSignupAssetVerificationTransportError(
                "Meta Embedded Signup asset verification transport failed"
            ) from None

        phone_ids, has_next_page = _parse_phone_numbers(body)
        if candidate_phone_number_id in phone_ids:
            return VerifiedEmbeddedSignupAssets(
                waba_id=candidate_waba_id,
                phone_number_id=candidate_phone_number_id,
            )
        if has_next_page:
            raise MetaEmbeddedSignupAssetPaginationIncompleteError(
                "Meta Embedded Signup asset verification requires another page"
            )
        # A mismatch is authoritative only after a structurally valid,
        # conclusively terminal enumeration has been validated in full.
        raise MetaEmbeddedSignupAssetMembershipMismatchError(
            "Meta Embedded Signup phone is not a member of the candidate WABA"
        )


def _validate_candidate_id(value: object) -> None:
    if not isinstance(value, str) or not _META_ID_PATTERN.fullmatch(value):
        raise MetaEmbeddedSignupAssetVerificationInputError(
            "Meta Embedded Signup candidate asset ID is invalid"
        )


def _parse_phone_numbers(body: bytes) -> tuple[set[str], bool]:
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MetaEmbeddedSignupAssetVerificationJSONError(
            "Meta Embedded Signup asset verification response JSON is invalid"
        ) from None
    if not isinstance(decoded, dict) or not isinstance(decoded.get("data"), list):
        raise MetaEmbeddedSignupAssetVerificationSchemaError(
            "Meta Embedded Signup asset verification response is invalid"
        )

    phone_ids: set[str] = set()
    for entry in decoded["data"]:
        if not isinstance(entry, dict):
            raise MetaEmbeddedSignupAssetVerificationSchemaError(
                "Meta Embedded Signup asset verification response is invalid"
            )
        phone_id = _parse_response_id(entry.get("id"))
        phone_ids.add(phone_id)

    return phone_ids, _has_next_page(decoded)


def _parse_response_id(value: object) -> str:
    if isinstance(value, bool):
        raise MetaEmbeddedSignupAssetVerificationSchemaError(
            "Meta Embedded Signup asset verification response is invalid"
        )
    if isinstance(value, int):
        parsed = str(value)
    elif isinstance(value, str):
        parsed = value
    else:
        raise MetaEmbeddedSignupAssetVerificationSchemaError(
            "Meta Embedded Signup asset verification response is invalid"
        )
    if not _META_ID_PATTERN.fullmatch(parsed):
        raise MetaEmbeddedSignupAssetVerificationSchemaError(
            "Meta Embedded Signup asset verification response is invalid"
        )
    return parsed


def _has_next_page(response: dict[str, object]) -> bool:
    """Return whether valid metadata proves another page exists.

    Missing pagination metadata is terminal. Once ``paging`` or one of its
    continuation fields is present, null and malformed values are not silently
    treated as terminal, because doing so could turn an ambiguous enumeration
    into an authoritative membership mismatch.
    """

    if "paging" not in response:
        return False
    paging = response["paging"]
    if not isinstance(paging, dict):
        raise MetaEmbeddedSignupAssetVerificationSchemaError(
            "Meta Embedded Signup asset verification response is invalid"
        )

    has_next_page = False
    if "next" in paging:
        next_url = paging["next"]
        if not isinstance(next_url, str) or not next_url:
            raise MetaEmbeddedSignupAssetVerificationSchemaError(
                "Meta Embedded Signup asset verification response is invalid"
            )
        has_next_page = True

    if "cursors" in paging:
        cursors = paging["cursors"]
        if not isinstance(cursors, dict):
            raise MetaEmbeddedSignupAssetVerificationSchemaError(
                "Meta Embedded Signup asset verification response is invalid"
            )
        if "after" in cursors:
            after = cursors["after"]
            if not isinstance(after, str) or not after:
                raise MetaEmbeddedSignupAssetVerificationSchemaError(
                    "Meta Embedded Signup asset verification response is invalid"
                )
            has_next_page = True

    return has_next_page
