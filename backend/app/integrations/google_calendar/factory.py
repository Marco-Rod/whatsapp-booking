from pathlib import Path

import httplib2
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build

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
