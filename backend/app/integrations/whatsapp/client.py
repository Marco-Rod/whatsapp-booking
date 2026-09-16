import logging
import re
import httpx

logger = logging.getLogger(__name__)


class WhatsAppConfigurationError(Exception):
    pass


class WhatsAppSendError(Exception):
    pass


class WhatsAppClient:
    def __init__(self, config, transport=None):
        self.config = config
        self.transport = transport

    async def send_text(self, phone: str, text: str) -> None:
        token = self.config.whatsapp_access_token.get_secret_value()
        number_id = self.config.whatsapp_phone_number_id
        version = self.config.whatsapp_api_version
        if not token or not re.fullmatch(r"[0-9]+", number_id) or not re.fullmatch(r"v[0-9]+\.[0-9]+", version):
            raise WhatsAppConfigurationError("WhatsApp sending is not configured")
        if not text or len(text) > 4096:
            raise WhatsAppSendError("Invalid outbound text length")
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=10) as client:
                response = await client.post(f"https://graph.facebook.com/{version}/{number_id}/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"messaging_product": "whatsapp", "to": phone.lstrip("+"),
                          "type": "text", "text": {"body": text}})
                response.raise_for_status()
                body = response.json()
                if not body.get("messages") or not body["messages"][0].get("id"):
                    raise ValueError("Missing message acknowledgement")
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "WhatsApp Graph API returned HTTP %s",
                exc.response.status_code,
            )
            raise WhatsAppSendError(
                "WhatsApp could not acknowledge the response"
            ) from None
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning(
                "WhatsApp send failed: %s",
                type(exc).__name__,
            )
            raise WhatsAppSendError(
                "WhatsApp could not acknowledge the response"
            ) from None
