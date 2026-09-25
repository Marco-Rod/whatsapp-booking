from fastapi import Response

from app.core.config import settings
from app.models import Business
from app.security.admin_sessions import AdminSessionError
from app.security.factory import build_admin_session_manager


ADMIN_SESSION_COOKIE = "admin_session"


def issue_admin_session_cookie(
    response: Response,
    business: Business,
) -> None:
    if business.admin_token_hash is None:
        raise AdminSessionError("Invalid admin session")

    manager = build_admin_session_manager()
    token = manager.create(
        business_id=business.id,
        admin_token_hash=business.admin_token_hash,
    )
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=token,
        max_age=manager.max_age_seconds,
        httponly=True,
        secure=settings.admin_session_cookie_secure,
        samesite=settings.admin_session_cookie_samesite,
        path="/",
    )


def expire_admin_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE,
        httponly=True,
        secure=settings.admin_session_cookie_secure,
        samesite=settings.admin_session_cookie_samesite,
        path="/",
    )
