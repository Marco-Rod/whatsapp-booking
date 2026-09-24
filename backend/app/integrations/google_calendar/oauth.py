from dataclasses import dataclass
import logging
import secrets

from google_auth_oauthlib.flow import Flow


logger = logging.getLogger(__name__)


GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
]


class GoogleOAuthConfigurationError(RuntimeError):
    pass


class GoogleOAuthExchangeError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoogleOAuthTokens:
    refresh_token: str | None
    scopes: list[str]


class GoogleOAuthService:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> None:
        if not client_id or not client_secret or not redirect_uri:
            raise GoogleOAuthConfigurationError(
                "Google OAuth configuration is incomplete"
            )

        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def generate_code_verifier(self) -> str:
        return secrets.token_urlsafe(64)

    def _build_flow(
        self,
        *,
        code_verifier: str | None = None,
    ) -> Flow:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=GOOGLE_CALENDAR_SCOPES,
            code_verifier=code_verifier,
            autogenerate_code_verifier=False,
        )

        flow.redirect_uri = self.redirect_uri
        return flow

    def build_authorization_url(
        self,
        *,
        state: str,
        code_verifier: str,
    ) -> str:
        if not state:
            raise ValueError("OAuth state is required")

        flow = self._build_flow(
            code_verifier=code_verifier,
        )

        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            state=state,
        )

        return authorization_url

    def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
    ) -> GoogleOAuthTokens:
        if not code:
            raise GoogleOAuthExchangeError(
                "Google OAuth authorization code is required"
            )

        if not code_verifier:
            raise GoogleOAuthExchangeError(
                "Google OAuth code verifier is required"
            )

        flow = self._build_flow(
            code_verifier=code_verifier,
        )

        try:
            flow.fetch_token(code=code)
        except Exception as exc:
            logger.exception("Google OAuth token exchange failed")
            raise GoogleOAuthExchangeError(
                "Unable to exchange Google OAuth authorization code"
            ) from exc

        credentials = flow.credentials

        return GoogleOAuthTokens(
            refresh_token=credentials.refresh_token,
            scopes=list(credentials.scopes or GOOGLE_CALENDAR_SCOPES),
        )
