from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.security.admin_tokens import (
    BusinessAdminAuthenticationError,
    authenticate_business_admin,
)
from app.security.admin_session_cookie import (
    expire_admin_session_cookie,
    issue_admin_session_cookie,
)


router = APIRouter(
    prefix="/admin/session",
    tags=["admin-session"],
)
bearer = HTTPBearer(auto_error=False)


@router.post("")
async def create_admin_session(
    response: Response,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    if credentials is None:
        raise _unauthorized()

    try:
        business = await authenticate_business_admin(
            session,
            credentials.credentials,
        )
    except BusinessAdminAuthenticationError:
        raise _unauthorized() from None

    issue_admin_session_cookie(response, business)
    return {"authenticated": True}


@router.delete("")
async def delete_admin_session(response: Response) -> dict[str, bool]:
    expire_admin_session_cookie(response)
    return {"authenticated": False}


def _unauthorized():
    return HTTPException(
        status_code=401,
        detail="Invalid business admin credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
