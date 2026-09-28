from fastapi import HTTPException, Request


async def read_bounded_request_body(
    request: Request,
    maximum_bytes: int,
    *,
    too_large_detail: str,
) -> bytes:
    """Read a request body without buffering more than ``maximum_bytes``."""
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > maximum_bytes:
                raise HTTPException(status_code=413, detail=too_large_detail)
        except ValueError:
            # Missing or malformed Content-Length is not trusted; stream instead.
            pass

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > maximum_bytes:
            raise HTTPException(status_code=413, detail=too_large_detail)
        chunks.append(chunk)
    return b"".join(chunks)
