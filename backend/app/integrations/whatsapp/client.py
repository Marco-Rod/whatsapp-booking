import logging
import re
import httpx

logger = logging.getLogger(__name__)


class WhatsAppConfigurationError(Exception):
    pass


class WhatsAppSendError(Exception):
    pass


def _to_meta_recipient(phone: str) -> str:
    """Convert our canonical phone representation to Meta's outbound recipient."""
    digits = phone.lstrip("+")

    # WhatsApp webhooks may represent Mexican mobile numbers as 521XXXXXXXXXX,
    # while Meta's test recipient allow-list expects 52XXXXXXXXXX.
    if digits.startswith("521") and len(digits) == 13:
        return "52" + digits[3:]

    return digits


class WhatsAppClient:
    """Meta client bound to one explicitly resolved business connection."""

    def __init__(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        api_version: str,
        transport=None,
    ):
        self.transport = transport
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._api_version = api_version

    def _credentials(self) -> tuple[str, str, str]:
        return self._access_token, self._phone_number_id, self._api_version

    async def send_text(self, phone: str, text: str) -> None:
        if phone.startswith("demo:"):
            raise WhatsAppSendError("Fictional demo contacts cannot receive messages")
        token, number_id, version = self._credentials()
        if not token or not re.fullmatch(r"[0-9]+", number_id) or not re.fullmatch(r"v[0-9]+\.[0-9]+", version):
            raise WhatsAppConfigurationError("WhatsApp sending is not configured")
        if not text or len(text) > 4096:
            raise WhatsAppSendError("Invalid outbound text length")
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=10) as client:
                response = await client.post(f"https://graph.facebook.com/{version}/{number_id}/messages",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"messaging_product": "whatsapp", "to": _to_meta_recipient(phone),
                          "type": "text", "text": {"body": text}})
                response.raise_for_status()
                body = response.json()
                if not body.get("messages") or not body["messages"][0].get("id"):
                    raise ValueError("Missing message acknowledgement")
        except httpx.HTTPStatusError as exc:
            error_code = None
            try:
                error_body = exc.response.json()
                error = error_body.get("error") if isinstance(error_body, dict) else None
                candidate = error.get("code") if isinstance(error, dict) else None
                if isinstance(candidate, int):
                    error_code = candidate
            except ValueError:
                pass
            logger.warning(
                "WhatsApp Graph API returned HTTP %s (code=%s)",
                exc.response.status_code, error_code,
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
