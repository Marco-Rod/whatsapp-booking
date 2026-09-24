from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.integrations.google_calendar.oauth_factory import (
    build_google_oauth_service,
)
from app.integrations.google_calendar.oauth import GoogleOAuthExchangeError
from app.models import Business, GoogleCalendarConnection
from app.security.factory import (
    build_credential_cipher,
    build_oauth_state_manager,
)
from app.security.oauth_state import OAuthStateError


router = APIRouter(
    prefix="/businesses/{business_id}/integrations/google",
    tags=["google-integrations"],
)

callback_router = APIRouter(
    prefix="/integrations/google",
    tags=["google-integrations"],
)


class GoogleIntegrationStatus(BaseModel):
    connected: bool
    calendar_id: str | None = None
    connected_at: datetime | None = None


class GoogleDisconnectResult(BaseModel):
    connected: bool


@router.get(
    "",
    response_model=GoogleIntegrationStatus,
)
async def get_google_integration_status(
    business_id: int,
    session: AsyncSession = Depends(get_session),
) -> GoogleIntegrationStatus:
    business = await session.get(Business, business_id)

    if business is None:
        raise HTTPException(
            status_code=404,
            detail="Business not found",
        )

    connection = await session.scalar(
        select(GoogleCalendarConnection).where(
            GoogleCalendarConnection.business_id
            == business_id
        )
    )

    if connection is None:
        return GoogleIntegrationStatus(
            connected=False,
        )

    return GoogleIntegrationStatus(
        connected=True,
        calendar_id=connection.calendar_id,
        connected_at=connection.connected_at,
    )


@router.delete(
    "",
    response_model=GoogleDisconnectResult,
)
async def disconnect_google_calendar(
    business_id: int,
    session: AsyncSession = Depends(get_session),
) -> GoogleDisconnectResult:
    business = await session.get(Business, business_id)

    if business is None:
        raise HTTPException(
            status_code=404,
            detail="Business not found",
        )

    connection = await session.scalar(
        select(GoogleCalendarConnection).where(
            GoogleCalendarConnection.business_id
            == business_id
        )
    )

    if connection is not None:
        await session.delete(connection)
        await session.commit()

    return GoogleDisconnectResult(
        connected=False,
    )


@router.get("/connect")
async def connect_google_calendar(
    business_id: int,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    business = await session.get(Business, business_id)

    if business is None:
        raise HTTPException(
            status_code=404,
            detail="Business not found",
        )

    state_manager = build_oauth_state_manager()
    oauth = build_google_oauth_service()

    code_verifier = oauth.generate_code_verifier()

    state = state_manager.create(
        business_id=business.id,
        code_verifier=code_verifier,
    )

    authorization_url = oauth.build_authorization_url(
        state=state,
        code_verifier=code_verifier,
    )

    return RedirectResponse(
        url=authorization_url,
        status_code=302,
    )


@callback_router.get("/callback")
async def google_calendar_callback(
    code: str,
    state: str,
    session: AsyncSession = Depends(get_session),
):
    state_manager = build_oauth_state_manager()

    try:
        oauth_state = state_manager.verify(state)
    except OAuthStateError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state",
        ) from exc

    business = await session.get(
        Business,
        oauth_state.business_id,
    )

    if business is None:
        raise HTTPException(
            status_code=404,
            detail="Business not found",
        )

    oauth = build_google_oauth_service()

    try:
        tokens = oauth.exchange_code(
            code=code,
            code_verifier=oauth_state.code_verifier,
        )
    except GoogleOAuthExchangeError as exc:
        raise HTTPException(
            status_code=400,
            detail="Unable to complete Google OAuth",
        ) from exc

    connection = await session.scalar(
        select(GoogleCalendarConnection).where(
            GoogleCalendarConnection.business_id
            == business.id
        )
    )

    if connection is None:
        if not tokens.refresh_token:
            raise HTTPException(
                status_code=400,
                detail="Google did not provide a refresh token",
            )

        cipher = build_credential_cipher()
        connection = GoogleCalendarConnection(
            business_id=business.id,
            calendar_id="primary",
            encrypted_refresh_token=cipher.encrypt(
                tokens.refresh_token
            ),
            scopes=tokens.scopes,
            connected_at=datetime.now(timezone.utc),
        )
        session.add(connection)
    else:
        if tokens.refresh_token:
            cipher = build_credential_cipher()
            connection.encrypted_refresh_token = cipher.encrypt(
                tokens.refresh_token
            )
        connection.calendar_id = "primary"
        connection.scopes = tokens.scopes
        connection.connected_at = datetime.now(timezone.utc)

    await session.commit()

    return {
        "status": "connected",
        "business_id": business.id,
    }
