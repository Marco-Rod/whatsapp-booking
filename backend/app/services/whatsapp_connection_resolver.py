from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WhatsAppConnection, WhatsAppConnectionStatus
from app.repositories.whatsapp_connections import WhatsAppConnectionRepository
from app.security.credentials import CredentialCipher
from app.security.factory import build_credential_cipher


@dataclass(frozen=True)
class ResolvedWhatsAppConnection:
    """Internal-only provider details for an active WhatsApp connection."""

    business_id: int
    waba_id: str
    phone_number_id: str
    display_phone_number: str | None
    access_token: str = field(repr=False)
    token_expires_at: datetime | None = None
    granted_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class WhatsAppRoutingIdentity:
    """Credential-free identity used to route authenticated inbound webhooks."""

    connection_id: int
    business_id: int
    phone_number_id: str
    status: str


class WhatsAppConnectionResolver:
    """Resolve active per-business connections without exposing credentials to APIs."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        cipher: CredentialCipher | None = None,
    ) -> None:
        self.repository = WhatsAppConnectionRepository(session)
        self.cipher = cipher

    def create_connection(
        self,
        *,
        business_id: int,
        waba_id: str,
        phone_number_id: str,
        access_token: str,
        display_phone_number: str | None = None,
        token_expires_at: datetime | None = None,
        granted_scopes: list[str] | None = None,
        status: WhatsAppConnectionStatus = WhatsAppConnectionStatus.PENDING,
        connected_at: datetime | None = None,
        disconnected_at: datetime | None = None,
    ) -> WhatsAppConnection:
        """Create an ORM record with its provider token encrypted at rest."""
        return WhatsAppConnection(
            business_id=business_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            display_phone_number=display_phone_number,
            encrypted_access_token=self._cipher().encrypt(access_token),
            token_expires_at=token_expires_at,
            granted_scopes=granted_scopes or [],
            status=status.value,
            connected_at=connected_at,
            disconnected_at=disconnected_at,
        )

    async def resolve_for_business(
        self,
        business_id: int,
    ) -> ResolvedWhatsAppConnection | None:
        connection = await self.repository.get_by_business_id(business_id)
        return self._resolve_active(connection)

    async def resolve_from_phone_number_id(
        self,
        phone_number_id: str,
    ) -> ResolvedWhatsAppConnection | None:
        connection = await self.repository.get_by_phone_number_id(
            phone_number_id
        )
        return self._resolve_active(connection)

    async def find_routing_identity(
        self,
        phone_number_id: str,
    ) -> WhatsAppRoutingIdentity | None:
        """Find any persisted connection without decrypting its credentials.

        Callers must accept only ``connected`` identities for provider routing.
        Returning inactive identities lets the webhook distinguish a deliberately
        disabled connection from a phone number with no persisted connection.
        """
        connection = await self.repository.get_by_phone_number_id(
            phone_number_id
        )
        if connection is None:
            return None

        return WhatsAppRoutingIdentity(
            connection_id=connection.id,
            business_id=connection.business_id,
            phone_number_id=connection.phone_number_id,
            status=connection.status,
        )

    async def find_routing_identity_for_business(
        self,
        business_id: int,
    ) -> WhatsAppRoutingIdentity | None:
        connection = await self.repository.get_by_business_id(business_id)
        if connection is None:
            return None
        return WhatsAppRoutingIdentity(
            connection_id=connection.id,
            business_id=connection.business_id,
            phone_number_id=connection.phone_number_id,
            status=connection.status,
        )

    def _resolve_active(
        self,
        connection: WhatsAppConnection | None,
    ) -> ResolvedWhatsAppConnection | None:
        if (
            connection is None
            or connection.status != WhatsAppConnectionStatus.CONNECTED.value
        ):
            return None

        return ResolvedWhatsAppConnection(
            business_id=connection.business_id,
            waba_id=connection.waba_id,
            phone_number_id=connection.phone_number_id,
            display_phone_number=connection.display_phone_number,
            access_token=self._cipher().decrypt(
                connection.encrypted_access_token
            ),
            token_expires_at=connection.token_expires_at,
            granted_scopes=tuple(connection.granted_scopes),
        )

    def _cipher(self) -> CredentialCipher:
        return self.cipher or build_credential_cipher()
