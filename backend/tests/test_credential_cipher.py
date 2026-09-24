import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.security import factory
from app.security.credentials import (
    CredentialCipher,
    CredentialDecryptionError,
    CredentialEncryptionError,
)


def make_cipher() -> CredentialCipher:
    key = Fernet.generate_key().decode("utf-8")
    return CredentialCipher(key)


def test_encrypt_does_not_return_plaintext():
    cipher = make_cipher()

    secret = "google-refresh-token-super-secret"

    encrypted = cipher.encrypt(secret)

    assert encrypted != secret
    assert secret not in encrypted


def test_encrypt_and_decrypt_round_trip():
    cipher = make_cipher()

    secret = "google-refresh-token-super-secret"

    encrypted = cipher.encrypt(secret)
    decrypted = cipher.decrypt(encrypted)

    assert decrypted == secret


def test_same_secret_produces_different_ciphertexts():
    cipher = make_cipher()

    secret = "same-secret"

    first = cipher.encrypt(secret)
    second = cipher.encrypt(secret)

    assert first != second

    assert cipher.decrypt(first) == secret
    assert cipher.decrypt(second) == secret


def test_different_key_cannot_decrypt():
    first = make_cipher()
    second = make_cipher()

    encrypted = first.encrypt("secret")

    with pytest.raises(CredentialDecryptionError):
        second.decrypt(encrypted)


def test_empty_secret_cannot_be_encrypted():
    cipher = make_cipher()

    with pytest.raises(CredentialEncryptionError):
        cipher.encrypt("")


def test_empty_ciphertext_cannot_be_decrypted():
    cipher = make_cipher()

    with pytest.raises(CredentialDecryptionError):
        cipher.decrypt("")


def test_invalid_key_is_rejected():
    with pytest.raises(CredentialEncryptionError):
        CredentialCipher("not-a-valid-fernet-key")


def test_build_credential_cipher_from_settings(monkeypatch):
    key = Fernet.generate_key().decode()

    monkeypatch.setattr(
        factory.settings,
        "credential_encryption_key",
        SecretStr(key),
    )

    cipher = factory.build_credential_cipher()

    encrypted = cipher.encrypt("refresh-token")

    assert encrypted != "refresh-token"
    assert cipher.decrypt(encrypted) == "refresh-token"


def test_build_credential_cipher_requires_configuration(monkeypatch):
    monkeypatch.setattr(
        factory.settings,
        "credential_encryption_key",
        None,
    )

    with pytest.raises(
        CredentialEncryptionError,
        match="Credential encryption is not configured",
    ):
        factory.build_credential_cipher()
