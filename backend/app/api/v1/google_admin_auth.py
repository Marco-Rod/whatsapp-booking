from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.core.config import Settings, settings
from app.core.database import get_session
from app.core.request_body import read_bounded_request_body
from app.core.rate_limit import FixedWindowRateLimiter, normalize_client_ip
from app.schemas.admin_auth import GoogleCredentialRequest
from app.security.admin_session_cookie import issue_admin_session_cookie
from app.security.factory import build_google_identity_verifier
from app.security.google_identity import GoogleIdentity, GoogleIdentityError
from app.services.google_admin_auth import (
    GoogleAdminAuthError,
    GoogleAdminAuthService,
)


router = APIRouter(
    prefix="/admin/google",
    tags=["google-admin-auth"],
)
bearer = HTTPBearer(auto_error=False)
GOOGLE_SESSION_LIMITER = FixedWindowRateLimiter(
    limit=12,
    window_seconds=600,
    capacity=4_096,
)
GOOGLE_LINK_LIMITER = FixedWindowRateLimiter(
    limit=5,
    window_seconds=1_800,
    capacity=4_096,
)


def get_google_admin_auth_settings() -> Settings:
    return settings


async def read_google_auth_body(
    request: Request,
    config: Annotated[Settings, Depends(get_google_admin_auth_settings)],
) -> bytes:
    try:
        raw_body = await read_bounded_request_body(
            request,
            config.google_admin_auth_max_body_bytes,
            too_large_detail="Google authentication payload too large",
        )
    except ClientDisconnect:
        raise HTTPException(
            status_code=400,
            detail="Request body was interrupted",
        ) from None

    return raw_body


def get_google_session_limiter() -> FixedWindowRateLimiter:
    return GOOGLE_SESSION_LIMITER


def get_google_link_limiter() -> FixedWindowRateLimiter:
    return GOOGLE_LINK_LIMITER


async def _rate_limit_google_auth(
    request: Request,
    raw_body: bytes,
    limiter: FixedWindowRateLimiter,
) -> bytes:
    retry_after = limiter.check(normalize_client_ip(request.client.host if request.client else None))
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many authentication attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    return raw_body


async def read_rate_limited_google_session_body(
    request: Request,
    raw_body: Annotated[bytes, Depends(read_google_auth_body)],
    limiter: Annotated[FixedWindowRateLimiter, Depends(get_google_session_limiter)],
) -> bytes:
    return await _rate_limit_google_auth(request, raw_body, limiter)


async def read_rate_limited_google_link_body(
    request: Request,
    raw_body: Annotated[bytes, Depends(read_google_auth_body)],
    limiter: Annotated[FixedWindowRateLimiter, Depends(get_google_link_limiter)],
) -> bytes:
    return await _rate_limit_google_auth(request, raw_body, limiter)


def _parse_google_credential(raw_body: bytes) -> GoogleCredentialRequest:
    try:
        return GoogleCredentialRequest.model_validate_json(raw_body)
    except ValidationError as exc:
        errors = []
        for error in exc.errors():
            errors.append({**error, "loc": ("body", *error["loc"])})
        raise RequestValidationError(errors) from None


async def read_rate_limited_google_session_credential(
    raw_body: Annotated[bytes, Depends(read_rate_limited_google_session_body)],
) -> GoogleCredentialRequest:
    return _parse_google_credential(raw_body)


async def read_rate_limited_google_link_credential(
    raw_body: Annotated[bytes, Depends(read_rate_limited_google_link_body)],
) -> GoogleCredentialRequest:
    return _parse_google_credential(raw_body)


async def verify_google_session_identity(
    credential_request: Annotated[
        GoogleCredentialRequest,
        Depends(read_rate_limited_google_session_credential),
    ],
) -> GoogleIdentity:
    try:
        return await build_google_identity_verifier().verify(
            credential_request.credential,
        )
    except GoogleIdentityError:
        raise _unauthorized() from None


async def require_bootstrap_bearer(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer),
    ],
) -> str:
    if credentials is None:
        raise _unauthorized()
    return credentials.credentials


@router.post("/link", status_code=204)
async def link_google_admin(
    credential_request: Annotated[
        GoogleCredentialRequest,
        Depends(read_rate_limited_google_link_credential),
    ],
    response: Response,
    admin_token: Annotated[str, Depends(require_bootstrap_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    try:
        result = await GoogleAdminAuthService(
            session,
            build_google_identity_verifier(),
        ).link_google_identity(
            admin_token=admin_token,
            google_credential=credential_request.credential,
        )
    except GoogleAdminAuthError:
        raise _unauthorized() from None

    issue_admin_session_cookie(response, result.business)


@router.post("/session", status_code=204)
async def create_google_admin_session(
    identity: Annotated[GoogleIdentity, Depends(verify_google_session_identity)],
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    try:
        result = await GoogleAdminAuthService(
            session,
            build_google_identity_verifier(),
        ).authenticate_google_identity(identity)
    except GoogleAdminAuthError:
        raise _unauthorized() from None

    issue_admin_session_cookie(response, result.business)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid Google admin authentication",
    )
