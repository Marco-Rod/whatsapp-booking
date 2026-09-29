"""Small, bounded response primitives shared by Meta Graph clients.

These helpers bound application-level raw response consumption. They do not
claim to bound lower-level network, TLS, or HTTP client buffers.
"""

import httpx


class MetaGraphResponseTooLargeError(Exception):
    """Raised before application code retains a response beyond its limit."""


def is_json_content_type(value: str | None) -> bool:
    if value is None:
        return False
    media_type = value.split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


def is_identity_content_encoding(value: str | None) -> bool:
    return value is None or value.strip().lower() == "identity"


async def read_bounded_raw_response(
    response: httpx.Response,
    maximum_bytes: int,
) -> bytes:
    """Read raw response chunks while enforcing ``maximum_bytes`` incrementally."""

    declared_length = response.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > maximum_bytes:
                raise MetaGraphResponseTooLargeError
        except ValueError:
            pass

    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_raw():
        if len(chunk) > maximum_bytes - size:
            raise MetaGraphResponseTooLargeError
        size += len(chunk)
        chunks.append(chunk)
    return b"".join(chunks)
