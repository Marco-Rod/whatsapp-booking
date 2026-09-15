import json
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.integrations.whatsapp.client import WhatsAppClient, WhatsAppConfigurationError, WhatsAppSendError
from app.integrations.whatsapp.signature import verify_webhook_signature
from app.services.whatsapp.webhook import WebhookService, verify_webhook

router = APIRouter()


def get_whatsapp_settings():
    return settings


def get_webhook_service(session: Annotated[AsyncSession, Depends(get_session)],
                        config=Depends(get_whatsapp_settings)):
    return WebhookService(session, WhatsAppClient(config), config)


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
async def receive(request: Request, service=Depends(get_webhook_service),
                  config=Depends(get_whatsapp_settings)):
    raw_body = await request.body()
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
        await service.process(payload)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid WhatsApp payload") from None
    except WhatsAppConfigurationError:
        raise HTTPException(status_code=503, detail="WhatsApp is not configured") from None
    except WhatsAppSendError:
        raise HTTPException(status_code=503, detail="Response delivery pending; retry required") from None
    return {"status": "ok"}
