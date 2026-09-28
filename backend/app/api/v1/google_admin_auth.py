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
from app.schemas.admin_auth import GoogleCredentialRequest
from app.security.admin_session_cookie import issue_admin_session_cookie
from app.security.factory import build_google_identity_verifier
from app.services.google_admin_auth import (
    GoogleAdminAuthError,
    GoogleAdminAuthService,
)


router = APIRouter(
    prefix="/admin/google",
    tags=["google-admin-auth"],
)
bearer = HTTPBearer(auto_error=False)


def get_google_admin_auth_settings() -> Settings:
    return settings


async def read_google_credential(
    request: Request,
    config: Annotated[Settings, Depends(get_google_admin_auth_settings)],
) -> GoogleCredentialRequest:
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

    try:
        return GoogleCredentialRequest.model_validate_json(raw_body)
    except ValidationError as exc:
        errors = []
        for error in exc.errors():
            errors.append({
                **error,
                "loc": ("body", *error["loc"]),
            })
        raise RequestValidationError(errors) from None


@router.post("/link", status_code=204)
async def link_google_admin(
    credential_request: Annotated[
        GoogleCredentialRequest,
        Depends(read_google_credential),
    ],
    response: Response,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    if credentials is None:
        raise _unauthorized()

    try:
        result = await GoogleAdminAuthService(
            session,
            build_google_identity_verifier(),
        ).link_google_identity(
            admin_token=credentials.credentials,
            google_credential=credential_request.credential,
        )
    except GoogleAdminAuthError:
        raise _unauthorized() from None

    issue_admin_session_cookie(response, result.business)


@router.post("/session", status_code=204)
async def create_google_admin_session(
    credential_request: Annotated[
        GoogleCredentialRequest,
        Depends(read_google_credential),
    ],
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    try:
        result = await GoogleAdminAuthService(
            session,
            build_google_identity_verifier(),
        ).authenticate_google(
            google_credential=credential_request.credential,
        )
    except GoogleAdminAuthError:
        raise _unauthorized() from None

    issue_admin_session_cookie(response, result.business)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid Google admin authentication",
    )
