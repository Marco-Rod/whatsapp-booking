import json
import logging
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import ClientDisconnect

from app.core.config import settings
from app.core.database import get_session
from app.core.request_body import read_bounded_request_body
from app.integrations.whatsapp.client import WhatsAppClient, WhatsAppConfigurationError, WhatsAppSendError
from app.integrations.whatsapp.signature import verify_webhook_signature
from app.services.calendar_resolver import CalendarClientResolver
from app.services.whatsapp.webhook import WebhookService, verify_webhook

router = APIRouter()
logger = logging.getLogger(__name__)


def get_whatsapp_settings():
    return settings


def log_whatsapp_configuration_error(error: WhatsAppConfigurationError) -> None:
    logger.warning(
        "WhatsApp configuration error (%s)",
        type(error).__name__,
    )


def create_webhook_service(session: AsyncSession, config):
    return WebhookService(
        session,
        WhatsAppClient(config),
        config,
        calendar_resolver=CalendarClientResolver(session),
    )


async def read_webhook_body(request: Request, maximum_bytes: int) -> bytes:
    return await read_bounded_request_body(
        request,
        maximum_bytes,
        too_large_detail="Webhook payload too large",
    )


async def process_signed_webhook(payload: dict, config) -> None:
    """Acquire database resources only after request authentication succeeds."""
    session_generator = get_session()
    try:
        session = await anext(session_generator)
        service = create_webhook_service(session, config)
        await service.process(payload)
    finally:
        await session_generator.aclose()


@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
async def verify(mode: Annotated[str, Query(alias="hub.mode")],
                 token: Annotated[str, Query(alias="hub.verify_token")],
                 challenge: Annotated[str, Query(alias="hub.challenge")],
                 config=Depends(get_whatsapp_settings)):
    try:
        return verify_webhook(config, mode, token, challenge)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Verification rejected") from None
    except WhatsAppConfigurationError:
        raise HTTPException(status_code=503, detail="Webhook is not configured") from None


@router.post("/webhooks/whatsapp")
async def receive(request: Request, config=Depends(get_whatsapp_settings)):
    try:
        raw_body = await read_webhook_body(
            request,
            config.whatsapp_webhook_max_body_bytes,
        )
    except ClientDisconnect:
        raise HTTPException(
            status_code=400,
            detail="Request body was interrupted",
        ) from None
    try:
        verify_webhook_signature(raw_body, request.headers.get("X-Hub-Signature-256"),
                                 config.meta_app_secret.get_secret_value())
    except PermissionError:
        raise HTTPException(status_code=403, detail="Webhook signature rejected") from None
    except WhatsAppConfigurationError:
        raise HTTPException(status_code=503, detail="Webhook signature verification is not configured") from None
    try:
        payload = json.loads(raw_body)
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        await process_signed_webhook(payload, config)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid WhatsApp payload") from None
    except WhatsAppConfigurationError as exc:
        log_whatsapp_configuration_error(exc)
        raise HTTPException(
            status_code=503,
            detail="WhatsApp is not configured",
        ) from None
    except WhatsAppSendError:
        raise HTTPException(status_code=503, detail="Response delivery pending; retry required") from None
    return {"status": "ok"}
