from datetime import date as Date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.api.v1.google_integrations import get_admin_business_id
from app.repositories.dashboard import DashboardRepository
from app.schemas.dashboard import DashboardResponse
from app.services.booking.availability import NotFoundError
from app.services.dashboard import DashboardService

admin_router = APIRouter(
    prefix="/admin/dashboard",
    tags=["dashboard"],
)


async def get_dashboard_response(
    business_id: int,
    date: Date,
    session: AsyncSession,
) -> DashboardResponse:
    try:
        return await DashboardService(
            DashboardRepository(session)
        ).get_dashboard(business_id, date)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@admin_router.get("", response_model=DashboardResponse)
async def admin_dashboard(
    date: Date,
    business_id: Annotated[int, Depends(get_admin_business_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DashboardResponse:
    return await get_dashboard_response(business_id, date, session)
