from fastapi import APIRouter, HTTPException, Response
from app.security.admin_session_cookie import (
    expire_admin_session_cookie,
)


router = APIRouter(
    prefix="/admin/session",
    tags=["admin-session"],
)


@router.post("", include_in_schema=False)
async def retired_admin_session_post() -> None:
    """Keep the removed login endpoint indistinguishable from an absent route."""
    raise HTTPException(status_code=404, detail="Not Found")


@router.delete("")
async def delete_admin_session(response: Response) -> dict[str, bool]:
    expire_admin_session_cookie(response)
    return {"authenticated": False}
