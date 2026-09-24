from collections.abc import Sequence
from pathlib import Path

import httplib2
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

from app.security.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
)

from .client import GoogleCalendarClient
from .errors import GoogleCalendarError


def calendar_client_from_token(token_file: str) -> GoogleCalendarClient:
    """Load a fresh credential/transport per worker call, never interactive OAuth.

    Refresh is handled by AuthorizedHttp. The local token file is not rewritten
    by concurrent workers; initial authorization remains a manual setup step.
    """
    path = Path(token_file).resolve()

    def service_factory():
        try:
            credentials = Credentials.from_authorized_user_file(str(path))
        except (OSError, ValueError):
            raise GoogleCalendarError("credentials") from None
        transport = AuthorizedHttp(credentials, http=httplib2.Http(timeout=20))
        try:
            return build("calendar", "v3", http=transport, cache_discovery=False,
                         static_discovery=True)
        except Exception:
            transport.close()
            raise

    return GoogleCalendarClient(service_factory)


def calendar_client_from_connection(
    *,
    encrypted_refresh_token: str,
    scopes: Sequence[str],
    cipher: CredentialCipher,
    client_id: str,
    client_secret: str,
) -> GoogleCalendarClient:
    """Build Calendar client from an encrypted OAuth refresh token.

    The refresh token is decrypted only inside the worker-side service factory.
    A fresh Credentials/AuthorizedHttp transport is created per operation.
    """

    if not encrypted_refresh_token:
        raise GoogleCalendarError("credentials")

    if not client_id or not client_secret:
        raise GoogleCalendarError("credentials")

    oauth_scopes = list(scopes)

    if not oauth_scopes:
        raise GoogleCalendarError("credentials")

    def service_factory():
        try:
            refresh_token = cipher.decrypt(
                encrypted_refresh_token
            )

            credentials = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=oauth_scopes,
            )
        except (CredentialDecryptionError, ValueError, TypeError):
            raise GoogleCalendarError(
                "credentials"
            ) from None

        transport = AuthorizedHttp(
            credentials,
            http=httplib2.Http(timeout=20),
        )

        try:
            return build(
                "calendar",
                "v3",
                http=transport,
                cache_discovery=False,
                static_discovery=True,
            )
        except Exception:
            transport.close()
            raise

    return GoogleCalendarClient(service_factory)
