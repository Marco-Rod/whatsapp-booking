"""One-shot, in-memory inspection of an Embedded Signup token with Meta."""

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


class MetaEmbeddedSignupTokenInspectionError(Exception):
    """Sanitized inspection failure; never include tokens or upstream bodies."""


class MetaEmbeddedSignupTokenInspectionConfigurationError(
    MetaEmbeddedSignupTokenInspectionError
):
    category = "configuration"


class MetaEmbeddedSignupTokenInspectionTransportError(
    MetaEmbeddedSignupTokenInspectionError
):
    category = "transport"


class MetaEmbeddedSignupTokenInspectionTimeoutError(
    MetaEmbeddedSignupTokenInspectionError
):
    category = "timeout"


class MetaEmbeddedSignupTokenInspectionUpstreamError(
    MetaEmbeddedSignupTokenInspectionError
):
    category = "upstream"

    def __init__(self, status_code: int) -> None:
        super().__init__("Meta Embedded Signup token inspection was rejected")
        self.status_code = status_code


class MetaEmbeddedSignupTokenInspectionResponseTooLargeError(
    MetaEmbeddedSignupTokenInspectionError
):
    category = "response_too_large"


class MetaEmbeddedSignupTokenInspectionContentTypeError(
    MetaEmbeddedSignupTokenInspectionError
):
    category = "invalid_content_type"


class MetaEmbeddedSignupTokenInspectionContentEncodingError(
    MetaEmbeddedSignupTokenInspectionError
):
    category = "invalid_content_encoding"


class MetaEmbeddedSignupTokenInspectionJSONError(
    MetaEmbeddedSignupTokenInspectionError
):
    category = "invalid_json"


class MetaEmbeddedSignupTokenInspectionSchemaError(
    MetaEmbeddedSignupTokenInspectionError
):
    category = "invalid_schema"


class MetaEmbeddedSignupTokenInvalidError(MetaEmbeddedSignupTokenInspectionError):
    category = "token_invalid"


class MetaEmbeddedSignupTokenAppMismatchError(
    MetaEmbeddedSignupTokenInspectionError
):
    category = "app_mismatch"


@dataclass(frozen=True)
class EmbeddedSignupGranularScope:
    scope: str
    target_ids: tuple[str, ...]


@dataclass(frozen=True)
class EmbeddedSignupTokenInspection:
    app_id: str
    token_type: str | None
    expires_at: int | None
    data_access_expires_at: int | None
    scopes: tuple[str, ...]
    granular_scopes: tuple[EmbeddedSignupGranularScope, ...]

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def target_ids_for_scope(self, scope: str) -> tuple[str, ...]:
        return tuple(
            target_id
            for granular_scope in self.granular_scopes
            if granular_scope.scope == scope
            for target_id in granular_scope.target_ids
        )


class MetaEmbeddedSignupTokenInspector:
    """Issue exactly one bounded ``debug_token`` request per invocation."""

    def __init__(
        self,
        *,
        app_id: str,
        provider_debug_token: SecretStr,
        graph_version: str,
        max_response_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not app_id or not provider_debug_token.get_secret_value():
            raise MetaEmbeddedSignupTokenInspectionConfigurationError(
                "Meta Embedded Signup token inspection is not configured"
            )
        if not _VERSION_PATTERN.fullmatch(graph_version):
            raise MetaEmbeddedSignupTokenInspectionConfigurationError(
                "Meta Embedded Signup token inspection version is invalid"
            )
        if max_response_bytes <= 0:
            raise MetaEmbeddedSignupTokenInspectionConfigurationError(
                "Meta Embedded Signup token inspection response limit is invalid"
            )

        self._app_id = app_id
        self._provider_debug_token = provider_debug_token
        self._graph_version = graph_version
        self._max_response_bytes = max_response_bytes
        self._transport = transport

    @property
    def inspection_url(self) -> str:
        return f"{_GRAPH_HOST}/{self._graph_version}/debug_token"

    async def inspect_token(
        self,
        access_token: SecretStr | str,
    ) -> EmbeddedSignupTokenInspection:
        token = (
            access_token.get_secret_value()
            if isinstance(access_token, SecretStr)
            else access_token
        )
        if not isinstance(token, str) or not token.strip():
            raise MetaEmbeddedSignupTokenInspectionSchemaError(
                "Meta Embedded Signup token inspection input is invalid"
            )

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
                    self.inspection_url,
                    params={"input_token": token},
                    headers={
                        "Authorization": (
                            "Bearer "
                            f"{self._provider_debug_token.get_secret_value()}"
                        ),
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    if response.status_code != httpx.codes.OK:
                        raise MetaEmbeddedSignupTokenInspectionUpstreamError(
                            response.status_code
                        )
                    if not is_json_content_type(response.headers.get("content-type")):
                        raise MetaEmbeddedSignupTokenInspectionContentTypeError(
                            "Meta Embedded Signup token inspection response is not JSON"
                        )
                    if not is_identity_content_encoding(
                        response.headers.get("content-encoding")
                    ):
                        raise MetaEmbeddedSignupTokenInspectionContentEncodingError(
                            "Meta Embedded Signup token inspection response encoding is unsupported"
                        )
                    try:
                        body = await read_bounded_raw_response(
                            response,
                            self._max_response_bytes,
                        )
                    except MetaGraphResponseTooLargeError:
                        raise MetaEmbeddedSignupTokenInspectionResponseTooLargeError(
                            "Meta Embedded Signup token inspection response is too large"
                        ) from None
        except MetaEmbeddedSignupTokenInspectionError:
            raise
        except httpx.TimeoutException:
            raise MetaEmbeddedSignupTokenInspectionTimeoutError(
                "Meta Embedded Signup token inspection timed out"
            ) from None
        except httpx.RequestError:
            raise MetaEmbeddedSignupTokenInspectionTransportError(
                "Meta Embedded Signup token inspection transport failed"
            ) from None

        return _parse_inspection(body, configured_app_id=self._app_id)


def _parse_inspection(
    body: bytes,
    *,
    configured_app_id: str,
) -> EmbeddedSignupTokenInspection:
    try:
        decoded = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MetaEmbeddedSignupTokenInspectionJSONError(
            "Meta Embedded Signup token inspection response JSON is invalid"
        ) from None
    if not isinstance(decoded, dict) or not isinstance(decoded.get("data"), dict):
        raise MetaEmbeddedSignupTokenInspectionSchemaError(
            "Meta Embedded Signup token inspection response is invalid"
        )

    data = decoded["data"]
    is_valid = data.get("is_valid")
    if not isinstance(is_valid, bool):
        raise MetaEmbeddedSignupTokenInspectionSchemaError(
            "Meta Embedded Signup token inspection response is invalid"
        )
    if not is_valid:
        raise MetaEmbeddedSignupTokenInvalidError(
            "Meta Embedded Signup token is invalid"
        )

    app_id = _parse_app_id(data.get("app_id"))
    if app_id != configured_app_id:
        raise MetaEmbeddedSignupTokenAppMismatchError(
            "Meta Embedded Signup token belongs to another app"
        )

    return EmbeddedSignupTokenInspection(
        app_id=app_id,
        token_type=_parse_optional_string(data, "type"),
        expires_at=_parse_optional_timestamp(data, "expires_at"),
        data_access_expires_at=_parse_optional_timestamp(
            data,
            "data_access_expires_at",
        ),
        scopes=_parse_optional_string_list(data, "scopes"),
        granular_scopes=_parse_optional_granular_scopes(data),
    )


def _parse_app_id(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MetaEmbeddedSignupTokenInspectionSchemaError(
            "Meta Embedded Signup token inspection response is invalid"
        )
    parsed = str(value)
    if not parsed:
        raise MetaEmbeddedSignupTokenInspectionSchemaError(
            "Meta Embedded Signup token inspection response is invalid"
        )
    return parsed


def _parse_optional_string(data: dict[str, object], key: str) -> str | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, str):
        raise MetaEmbeddedSignupTokenInspectionSchemaError(
            "Meta Embedded Signup token inspection response is invalid"
        )
    return value


def _parse_optional_timestamp(data: dict[str, object], key: str) -> int | None:
    if key not in data:
        return None
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MetaEmbeddedSignupTokenInspectionSchemaError(
            "Meta Embedded Signup token inspection response is invalid"
        )
    return value


def _parse_optional_string_list(data: dict[str, object], key: str) -> tuple[str, ...]:
    if key not in data:
        return ()
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MetaEmbeddedSignupTokenInspectionSchemaError(
            "Meta Embedded Signup token inspection response is invalid"
        )
    return tuple(value)


def _parse_optional_granular_scopes(
    data: dict[str, object],
) -> tuple[EmbeddedSignupGranularScope, ...]:
    if "granular_scopes" not in data:
        return ()
    raw_scopes = data["granular_scopes"]
    if not isinstance(raw_scopes, list):
        raise MetaEmbeddedSignupTokenInspectionSchemaError(
            "Meta Embedded Signup token inspection response is invalid"
        )

    parsed: list[EmbeddedSignupGranularScope] = []
    for raw_scope in raw_scopes:
        if not isinstance(raw_scope, dict) or not isinstance(raw_scope.get("scope"), str):
            raise MetaEmbeddedSignupTokenInspectionSchemaError(
                "Meta Embedded Signup token inspection response is invalid"
            )
        raw_target_ids = raw_scope.get("target_ids", [])
        if not isinstance(raw_target_ids, list) or not all(
            isinstance(target_id, str) for target_id in raw_target_ids
        ):
            raise MetaEmbeddedSignupTokenInspectionSchemaError(
                "Meta Embedded Signup token inspection response is invalid"
            )
        parsed.append(
            EmbeddedSignupGranularScope(
                scope=raw_scope["scope"],
                target_ids=tuple(raw_target_ids),
            )
        )
    return tuple(parsed)
