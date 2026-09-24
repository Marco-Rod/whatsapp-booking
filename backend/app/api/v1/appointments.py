from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.services.booking.calendar import BookingCalendarSync
from app.services.calendar_resolver import CalendarClientResolver
from app.schemas.booking import AppointmentCreate, AppointmentReschedule, AppointmentResponse
from app.services.booking.availability import NotFoundError
from app.services.booking.booking import BookingConflictError, BookingService

router = APIRouter()


def get_calendar_resolver(
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return CalendarClientResolver(session)


@router.post("/appointments", response_model=AppointmentResponse, status_code=201)
async def create_appointment(request: AppointmentCreate,
                             session: Annotated[AsyncSession, Depends(get_session)],
                             resolver: Annotated[CalendarClientResolver, Depends(get_calendar_resolver)]):
    try:
        response = await BookingService(session).create_appointment(request)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await BookingCalendarSync(session, resolver).created(response.id)
    return response


@router.get("/appointments/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(appointment_id: int,
                          session: Annotated[AsyncSession, Depends(get_session)]):
    try:
        return await BookingService(session).get_appointment(appointment_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/appointments/{appointment_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment(appointment_id: int,
                             session: Annotated[AsyncSession, Depends(get_session)],
                             resolver: Annotated[CalendarClientResolver, Depends(get_calendar_resolver)]):
    try:
        result = await BookingService(session).cancel_appointment_with_result(appointment_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if result.was_cancelled_now:
        await BookingCalendarSync(session, resolver).cancelled(appointment_id)
    return result.appointment


@router.post("/appointments/{appointment_id}/reschedule", response_model=AppointmentResponse)
async def reschedule_appointment(appointment_id: int, request: AppointmentReschedule,
                                 session: Annotated[AsyncSession, Depends(get_session)],
                                 resolver: Annotated[CalendarClientResolver, Depends(get_calendar_resolver)]):
    try:
        response = await BookingService(session).reschedule_appointment(appointment_id, request)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await BookingCalendarSync(session, resolver).rescheduled(appointment_id)
    return response
