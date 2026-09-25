from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.onboarding import (
    BusinessConfigurationRequest,
    BusinessHoursConfigurationRequest,
    OnboardingStatus,
    ServicesConfigurationRequest,
)
from app.security.admin_sessions import (
    AdminSessionError,
    authenticate_admin_session,
)
from app.security.factory import build_admin_session_manager
from app.services.onboarding import (
    OnboardingConfigurationError,
    OnboardingIncompleteError,
    OnboardingService,
)


router = APIRouter(
    prefix="/onboarding",
    tags=["onboarding"],
)
async def get_business_admin_id(
    session: Annotated[AsyncSession, Depends(get_session)],
    admin_session: Annotated[str | None, Cookie()] = None,
) -> int:
    if admin_session is None:
        raise unauthorized_admin()

    try:
        business = await authenticate_admin_session(
            session,
            admin_session,
            build_admin_session_manager(),
        )
    except AdminSessionError:
        raise unauthorized_admin() from None

    business_id = business.id
    await session.rollback()
    return business_id


def unauthorized_admin() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Invalid business admin credentials",
    )


def _invalid_configuration(
    error: OnboardingConfigurationError,
) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail=str(error),
    )


@router.get("/status", response_model=OnboardingStatus)
async def get_onboarding_status(
    business_id: Annotated[int, Depends(get_business_admin_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingStatus:
    return await OnboardingService(session).get_status(business_id)


@router.put("/business", response_model=OnboardingStatus)
async def configure_onboarding_business(
    request: BusinessConfigurationRequest,
    business_id: Annotated[int, Depends(get_business_admin_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingStatus:
    service = OnboardingService(session)
    try:
        await service.configure_business(
            business_id,
            name=request.name,
            timezone_name=request.timezone,
        )
    except OnboardingConfigurationError as exc:
        raise _invalid_configuration(exc) from exc
    return await service.get_status(business_id)


@router.put("/services", response_model=OnboardingStatus)
async def configure_onboarding_services(
    request: ServicesConfigurationRequest,
    business_id: Annotated[int, Depends(get_business_admin_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingStatus:
    service = OnboardingService(session)
    try:
        await service.replace_services(
            business_id,
            request.services,
        )
    except OnboardingConfigurationError as exc:
        raise _invalid_configuration(exc) from exc
    return await service.get_status(business_id)


@router.put("/hours", response_model=OnboardingStatus)
async def configure_onboarding_hours(
    request: BusinessHoursConfigurationRequest,
    business_id: Annotated[int, Depends(get_business_admin_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingStatus:
    service = OnboardingService(session)
    try:
        await service.replace_business_hours(
            business_id,
            request.hours,
        )
    except OnboardingConfigurationError as exc:
        raise _invalid_configuration(exc) from exc
    return await service.get_status(business_id)


@router.post("/complete", response_model=OnboardingStatus)
async def complete_onboarding(
    business_id: Annotated[int, Depends(get_business_admin_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        return await OnboardingService(
            session
        ).complete_onboarding(business_id)
    except OnboardingIncompleteError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Onboarding is incomplete",
                "missing_steps": list(exc.missing_steps),
            },
        )
