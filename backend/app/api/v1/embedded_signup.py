from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.api.v1.google_integrations import get_admin_business_id
from app.core.config import Settings, settings
from app.core.database import get_session
from app.core.request_body import read_bounded_request_body
from app.schemas.embedded_signup import (
    EmbeddedSignupCompleteRequest,
    EmbeddedSignupStartResponse,
)
from app.services.embedded_signup import (
    EmbeddedSignupAttemptConsumedError,
    EmbeddedSignupAttemptExpiredError,
    EmbeddedSignupAttemptNotFoundError,
    EmbeddedSignupAttemptOwnershipError,
    EmbeddedSignupAttemptService,
)


router = APIRouter(
    prefix="/admin/whatsapp/embedded-signup",
    tags=["embedded-signup"],
)


def get_embedded_signup_settings() -> Settings:
    return settings


async def read_embedded_signup_body(
    request: Request,
    config: Annotated[Settings, Depends(get_embedded_signup_settings)],
) -> bytes:
    try:
        return await read_bounded_request_body(
            request,
            config.embedded_signup_max_body_bytes,
            too_large_detail="Embedded Signup payload too large",
        )
    except ClientDisconnect:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body was interrupted",
        ) from None


def _parse_completion(raw_body: bytes) -> EmbeddedSignupCompleteRequest:
    try:
        return EmbeddedSignupCompleteRequest.model_validate_json(raw_body)
    except ValidationError as exc:
        errors = [
            {
                key: value
                for key, value in error.items()
                if key != "input"
            }
            | {"loc": ("body", *error["loc"])}
            for error in exc.errors()
        ]
        raise RequestValidationError(errors) from None


async def read_embedded_signup_completion(
    raw_body: Annotated[bytes, Depends(read_embedded_signup_body)],
) -> EmbeddedSignupCompleteRequest:
    return _parse_completion(raw_body)


@router.post("/start", response_model=EmbeddedSignupStartResponse)
async def start_embedded_signup(
    business_id: Annotated[int, Depends(get_admin_business_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
    config: Annotated[Settings, Depends(get_embedded_signup_settings)],
) -> EmbeddedSignupStartResponse:
    attempt = await EmbeddedSignupAttemptService(
        session,
        ttl_seconds=config.embedded_signup_attempt_ttl_seconds,
    ).start(business_id)
    return EmbeddedSignupStartResponse(
        nonce=attempt.nonce,
        expires_at=attempt.expires_at,
    )


@router.post("/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_embedded_signup(
    completion: Annotated[
        EmbeddedSignupCompleteRequest,
        Depends(read_embedded_signup_completion),
    ],
    business_id: Annotated[int, Depends(get_admin_business_id)],
    session: Annotated[AsyncSession, Depends(get_session)],
    config: Annotated[Settings, Depends(get_embedded_signup_settings)],
) -> None:
    try:
        await EmbeddedSignupAttemptService(
            session,
            ttl_seconds=config.embedded_signup_attempt_ttl_seconds,
        ).complete(
            business_id=business_id,
            attempt_nonce=completion.attempt_nonce,
            authorization_code=completion.authorization_code,
            candidate_account_id=completion.candidate_account_id,
            candidate_phone_number_id=completion.candidate_phone_number_id,
        )
    except EmbeddedSignupAttemptNotFoundError:
        raise _invalid_attempt() from None
    except EmbeddedSignupAttemptOwnershipError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Embedded Signup attempt access denied",
        ) from None
    except EmbeddedSignupAttemptExpiredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Embedded Signup attempt expired",
        ) from None
    except EmbeddedSignupAttemptConsumedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Embedded Signup attempt already consumed",
        ) from None


def _invalid_attempt() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid Embedded Signup attempt",
    )
