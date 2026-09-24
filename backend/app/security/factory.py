import hashlib

from app.core.config import settings
from app.security.credentials import (
    CredentialCipher,
    CredentialEncryptionError,
)
from app.security.oauth_state import OAuthStateManager


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
