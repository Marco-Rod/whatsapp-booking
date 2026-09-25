from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
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


@router.post("/link", status_code=204)
async def link_google_admin(
    request: GoogleCredentialRequest,
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
            google_credential=request.credential,
        )
    except GoogleAdminAuthError:
        raise _unauthorized() from None

    issue_admin_session_cookie(response, result.business)


@router.post("/session", status_code=204)
async def create_google_admin_session(
    request: GoogleCredentialRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    try:
        result = await GoogleAdminAuthService(
            session,
            build_google_identity_verifier(),
        ).authenticate_google(
            google_credential=request.credential,
        )
    except GoogleAdminAuthError:
        raise _unauthorized() from None

    issue_admin_session_cookie(response, result.business)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid Google admin authentication",
    )
