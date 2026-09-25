import hashlib

from app.core.config import settings
from app.security.credentials import (
    CredentialCipher,
    CredentialEncryptionError,
)
from app.security.oauth_state import OAuthStateManager
from app.security.admin_sessions import (
    AdminSessionError,
    AdminSessionManager,
)
from app.security.google_identity import (
    GoogleIdentityError,
    GoogleIdentityVerifier,
)


def build_credential_cipher() -> CredentialCipher:
    secret = settings.credential_encryption_key

    if secret is None:
        raise CredentialEncryptionError(
            "Credential encryption is not configured"
        )

    return CredentialCipher(secret.get_secret_value())


def build_oauth_state_manager() -> OAuthStateManager:
    secret = settings.credential_encryption_key

    if secret is None:
        raise CredentialEncryptionError(
            "Credential encryption is not configured"
        )

    key = secret.get_secret_value()

    state_secret = hashlib.sha256(
        f"oauth-state:{key}".encode("utf-8")
    ).hexdigest()

    return OAuthStateManager(
        secret=state_secret,
        max_age_seconds=600,
    )


def build_admin_session_manager() -> AdminSessionManager:
    secret = settings.admin_session_secret
    if secret is None:
        raise AdminSessionError(
            "Admin sessions are not configured"
        )
    return AdminSessionManager(
        secret=secret.get_secret_value(),
        max_age_seconds=settings.admin_session_max_age_seconds,
    )


def build_google_identity_verifier() -> GoogleIdentityVerifier:
    client_id = settings.google_identity_client_id
    if client_id is None or not client_id.strip():
        raise GoogleIdentityError("Invalid Google identity")
    return GoogleIdentityVerifier(client_id=client_id)
