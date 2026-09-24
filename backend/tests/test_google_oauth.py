import pytest

from app.integrations.google_calendar.oauth import (
    GOOGLE_CALENDAR_SCOPES,
    GoogleOAuthConfigurationError,
    GoogleOAuthService,
)


def make_service() -> GoogleOAuthService:
    return GoogleOAuthService(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="https://example.com/oauth/callback",
    )


def test_google_oauth_requires_configuration():
    with pytest.raises(GoogleOAuthConfigurationError):
        GoogleOAuthService(
            client_id="",
            client_secret="secret",
            redirect_uri="https://example.com/callback",
        )


def test_build_authorization_url():
    service = make_service()

    url = service.build_authorization_url(
        state="signed-test-state",
        code_verifier="test-code-verifier",
    )

    assert url.startswith(
        "https://accounts.google.com/o/oauth2/auth"
    )

    assert "client_id=test-client-id" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=signed-test-state" in url
    assert "include_granted_scopes=true" not in url
    assert "code_challenge=" in url
    assert "code_challenge_method=S256" in url


def test_authorization_requires_state():
    service = make_service()

    with pytest.raises(
        ValueError,
        match="OAuth state is required",
    ):
        service.build_authorization_url(
            state="",
            code_verifier="test-code-verifier",
        )


def test_google_calendar_uses_limited_scope():
    assert GOOGLE_CALENDAR_SCOPES == [
        "https://www.googleapis.com/auth/calendar.events"
    ]
