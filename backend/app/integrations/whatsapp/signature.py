import hashlib
import hmac
import re

from app.integrations.whatsapp.client import WhatsAppConfigurationError


def verify_webhook_signature(raw_body: bytes, signature: str | None, app_secret: str) -> None:
    """Authenticate the exact request bytes before parsing any JSON."""
    if not app_secret:
        raise WhatsAppConfigurationError("Meta app secret is not configured")
    if signature is None or re.fullmatch(r"sha256=[0-9a-fA-F]{64}", signature) is None:
        raise PermissionError("Invalid webhook signature")
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    supplied = bytes.fromhex(signature[len("sha256="):])
    if not hmac.compare_digest(expected, supplied):
        raise PermissionError("Invalid webhook signature")
