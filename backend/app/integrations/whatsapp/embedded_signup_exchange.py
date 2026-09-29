"""One-shot, server-side exchange for Meta Embedded Signup codes.

This module deliberately owns no persistence and performs no retries.  The
authorization-code lifecycle is not sufficiently documented to replay a code
after any failure.
"""

from dataclasses import dataclass
import json
import re

import httpx
from pydantic import SecretStr


_GRAPH_HOST = "https://graph.facebook.com"
_VERSION_PATTERN = re.compile(r"v[0-9]+\.[0-9]+$")
_MAX_AUTHORIZATION_CODE_LENGTH = 4_096


class MetaEmbeddedSignupExchangeError(RuntimeError):
    """Sanitized exchange failure; never include upstream bodies or secrets."""

    category = "exchange_failed"

    def __init__(self, message: str = "Meta Embedded Signup exchange failed") -> None:
        super().__init__(message)


class MetaEmbeddedSignupExchangeConfigurationError(MetaEmbeddedSignupExchangeError):
    category = "configuration"


class MetaEmbeddedSignupExchangeTransportError(MetaEmbeddedSignupExchangeError):
    category = "transport"


class MetaEmbeddedSignupExchangeTimeoutError(MetaEmbeddedSignupExchangeError):
    category = "timeout"


class MetaEmbeddedSignupExchangeUpstreamError(MetaEmbeddedSignupExchangeError):
    category = "upstream"

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__("Meta Embedded Signup exchange was rejected")


class MetaEmbeddedSignupExchangeResponseTooLargeError(MetaEmbeddedSignupExchangeError):
    category = "response_too_large"


class MetaEmbeddedSignupExchangeContentTypeError(MetaEmbeddedSignupExchangeError):
    category = "invalid_content_type"


class MetaEmbeddedSignupExchangeContentEncodingError(MetaEmbeddedSignupExchangeError):
    category = "invalid_content_encoding"


class MetaEmbeddedSignupExchangeJSONError(MetaEmbeddedSignupExchangeError):
    category = "invalid_json"


class MetaEmbeddedSignupExchangeResponseError(MetaEmbeddedSignupExchangeError):
    category = "invalid_response"


@dataclass(frozen=True)
class EmbeddedSignupExchangeToken:
    """The opaque token is intentionally repr-safe and not persisted here."""

    access_token: SecretStr


class MetaEmbeddedSignupExchangeClient:
    """Perform exactly one Meta authorization-code exchange HTTP request."""

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: SecretStr,
        redirect_uri: str,
        graph_version: str,
        max_response_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not app_id or not app_secret.get_secret_value() or not redirect_uri:
            raise MetaEmbeddedSignupExchangeConfigurationError(
                "Meta Embedded Signup exchange is not configured"
            )
        if not _VERSION_PATTERN.fullmatch(graph_version):
            raise MetaEmbeddedSignupExchangeConfigurationError(
                "Meta Embedded Signup exchange version is invalid"
            )
        if max_response_bytes <= 0:
            raise MetaEmbeddedSignupExchangeConfigurationError(
                "Meta Embedded Signup response limit is invalid"
            )

        self._app_id = app_id
        self._app_secret = app_secret
        self._redirect_uri = redirect_uri
        self._graph_version = graph_version
        self._max_response_bytes = max_response_bytes
        self._transport = transport

    @property
    def exchange_url(self) -> str:
        return f"{_GRAPH_HOST}/{self._graph_version}/oauth/access_token"

    async def exchange_authorization_code(
        self,
        authorization_code: SecretStr | str,
    ) -> EmbeddedSignupExchangeToken:
        code = (
            authorization_code.get_secret_value()
            if isinstance(authorization_code, SecretStr)
            else authorization_code
        )
        if not isinstance(code, str) or not code or len(code) > _MAX_AUTHORIZATION_CODE_LENGTH:
            raise MetaEmbeddedSignupExchangeResponseError(
                "Authorization code is invalid"
            )

        payload = {
            "client_id": self._app_id,
            "client_secret": self._app_secret.get_secret_value(),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self._redirect_uri,
        }
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=10.0)
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    self.exchange_url,
                    headers={
                        "Content-Type": "application/json",
                        "Accept-Encoding": "identity",
                    },
                    json=payload,
                ) as response:
                    if response.status_code != httpx.codes.OK:
                        raise MetaEmbeddedSignupExchangeUpstreamError(
                            response.status_code
                        )
                    if not _is_json_content_type(response.headers.get("content-type")):
                        raise MetaEmbeddedSignupExchangeContentTypeError(
                            "Meta Embedded Signup response is not JSON"
                        )
                    if not _is_identity_content_encoding(
                        response.headers.get("content-encoding")
                    ):
                        raise MetaEmbeddedSignupExchangeContentEncodingError(
                            "Meta Embedded Signup response encoding is unsupported"
                        )
                    body = await _read_bounded_response(
                        response,
                        self._max_response_bytes,
                    )
        except MetaEmbeddedSignupExchangeError:
            raise
        except httpx.TimeoutException:
            raise MetaEmbeddedSignupExchangeTimeoutError(
                "Meta Embedded Signup exchange timed out"
            ) from None
        except httpx.RequestError:
            raise MetaEmbeddedSignupExchangeTransportError(
                "Meta Embedded Signup exchange transport failed"
            ) from None

        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MetaEmbeddedSignupExchangeJSONError(
                "Meta Embedded Signup response JSON is invalid"
            ) from None
        if not isinstance(decoded, dict):
            raise MetaEmbeddedSignupExchangeResponseError(
                "Meta Embedded Signup response is invalid"
            )
        token = decoded.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise MetaEmbeddedSignupExchangeResponseError(
                "Meta Embedded Signup response is invalid"
            )
        return EmbeddedSignupExchangeToken(access_token=SecretStr(token))


def _is_json_content_type(value: str | None) -> bool:
    if value is None:
        return False
    media_type = value.split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


def _is_identity_content_encoding(value: str | None) -> bool:
    return value is None or value.strip().lower() == "identity"


async def _read_bounded_response(
    response: httpx.Response,
    maximum_bytes: int,
) -> bytes:
    declared_length = response.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > maximum_bytes:
                raise MetaEmbeddedSignupExchangeResponseTooLargeError(
                    "Meta Embedded Signup response is too large"
                )
        except ValueError:
            pass

    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_raw():
        if len(chunk) > maximum_bytes - size:
            raise MetaEmbeddedSignupExchangeResponseTooLargeError(
                "Meta Embedded Signup response is too large"
            )
        size += len(chunk)
        chunks.append(chunk)
    return b"".join(chunks)
