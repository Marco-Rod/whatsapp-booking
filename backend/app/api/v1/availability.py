from datetime import date as Date
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.database import get_session
from app.repositories.availability import AvailabilityRepository
from app.schemas.availability import AvailabilityResponse
from app.services.booking.availability import AvailabilityService, NotFoundError

router = APIRouter()


@router.get("/availability", response_model=AvailabilityResponse)
async def availability(business_id: Annotated[int, Query(gt=0)],
                       service_id: Annotated[int, Query(gt=0)], date: Date,
                       session: Annotated[AsyncSession, Depends(get_session)]):
    try:
        return await AvailabilityService(AvailabilityRepository(session), settings.slot_interval_minutes).get_available_slots(business_id, service_id, date)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
