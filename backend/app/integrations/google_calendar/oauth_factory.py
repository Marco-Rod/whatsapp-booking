from app.core.config import settings
from app.integrations.google_calendar.oauth import (
    GoogleOAuthConfigurationError,
    GoogleOAuthService,
)


def build_google_oauth_service() -> GoogleOAuthService:
    client_id = settings.google_oauth_client_id
    client_secret = settings.google_oauth_client_secret
    redirect_uri = settings.google_oauth_redirect_uri

    if client_id is None or client_secret is None or not redirect_uri:
        raise GoogleOAuthConfigurationError(
            "Google OAuth is not configured"
        )

    return GoogleOAuthService(
        client_id=client_id.get_secret_value(),
        client_secret=client_secret.get_secret_value(),
        redirect_uri=redirect_uri,
    )
