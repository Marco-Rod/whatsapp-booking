from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.whatsapp.client import (
    WhatsAppClient,
    WhatsAppConfigurationError,
    WhatsAppSendError,
)
from app.models import WhatsAppConnectionStatus
from app.security.credentials import CredentialDecryptionError
from app.services.whatsapp_connection_resolver import WhatsAppConnectionResolver


class WhatsAppChannelUnavailable(WhatsAppSendError):
    """The requested business has no usable WhatsApp delivery channel."""


class WhatsAppSender:
    """Send only through the connection belonging to the requested business."""

    def __init__(self, session: AsyncSession, config, *, resolver=None,
                 client_factory=WhatsAppClient):
        self.config = config
        self.resolver = resolver or WhatsAppConnectionResolver(session)
        self.client_factory = client_factory

    async def send_for_business(self, business_id: int, recipient: str, text: str) -> None:
        routing = await self.resolver.find_routing_identity_for_business(business_id)
        if routing is not None:
            if routing.status != WhatsAppConnectionStatus.CONNECTED.value:
                raise WhatsAppChannelUnavailable("WhatsApp connection is not active")
            try:
                connection = await self.resolver.resolve_for_business(business_id)
            except CredentialDecryptionError:
                raise WhatsAppChannelUnavailable("WhatsApp connection credentials are unavailable") from None
            if connection is None:
                raise WhatsAppChannelUnavailable("WhatsApp connection is not active")
            client = self.client_factory(
                access_token=connection.access_token,
                phone_number_id=connection.phone_number_id,
                api_version=self.config.whatsapp_api_version,
            )
            await client.send_text(recipient, text)
            return

        if self.config.whatsapp_legacy_business_id == business_id:
            await self.client_factory(self.config).send_text(recipient, text)
            return

        raise WhatsAppChannelUnavailable("Business has no WhatsApp connection")
