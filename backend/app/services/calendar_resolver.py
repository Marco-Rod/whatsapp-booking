from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.google_calendar.client import GoogleCalendarClient
from app.integrations.google_calendar.errors import GoogleCalendarError
from app.integrations.google_calendar.factory import (
    calendar_client_from_connection,
    calendar_client_from_token,
)
from app.models import Business, GoogleCalendarConnection
from app.security.credentials import CredentialCipher
from app.security.factory import build_credential_cipher


@dataclass(frozen=True)
class ResolvedCalendar:
    calendar_id: str
    client: GoogleCalendarClient
    source: str


class CalendarClientResolver:
    def __init__(
        self,
        session: AsyncSession,
        *,
        cipher: CredentialCipher | None = None,
    ) -> None:
        self.session = session
        self.cipher = cipher

    async def resolve(
        self,
        business_id: int,
    ) -> ResolvedCalendar | None:
        connection = await self.session.scalar(
            select(GoogleCalendarConnection).where(
                GoogleCalendarConnection.business_id
                == business_id
            )
        )

        if connection is not None:
            client_id = settings.google_oauth_client_id
            client_secret = settings.google_oauth_client_secret

            if client_id is None or client_secret is None:
                raise GoogleCalendarError("credentials")

            client = calendar_client_from_connection(
                encrypted_refresh_token=(
                    connection.encrypted_refresh_token
                ),
                scopes=connection.scopes,
                cipher=self.cipher or build_credential_cipher(),
                client_id=client_id.get_secret_value(),
                client_secret=client_secret.get_secret_value(),
            )

            return ResolvedCalendar(
                calendar_id=connection.calendar_id,
                client=client,
                source="oauth",
            )

        business = await self.session.get(
            Business,
            business_id,
        )

        if business is None or not business.calendar_id:
            return None

        return ResolvedCalendar(
            calendar_id=business.calendar_id,
            client=calendar_client_from_token(
                settings.google_calendar_token_file
            ),
            source="legacy",
        )
