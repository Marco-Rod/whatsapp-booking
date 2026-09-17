from datetime import date as Date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.repositories.dashboard import DashboardRepository
from app.schemas.dashboard import DashboardResponse
from app.services.booking.availability import NotFoundError
from app.services.dashboard import DashboardService

router = APIRouter()


@router.get("/businesses/{business_id}/dashboard", response_model=DashboardResponse)
async def dashboard(business_id: Annotated[int, Path(gt=0)], date: Date,
                    session: Annotated[AsyncSession, Depends(get_session)]):
    try:
        return await DashboardService(DashboardRepository(session)).get_dashboard(business_id, date)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
