from cryptography.fernet import Fernet, InvalidToken


class CredentialEncryptionError(RuntimeError):
    pass


class CredentialDecryptionError(RuntimeError):
    pass


class CredentialCipher:
    def __init__(self, key: str) -> None:
        if not key:
            raise CredentialEncryptionError(
                "Credential encryption key is required"
            )

        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise CredentialEncryptionError(
                "Invalid credential encryption key"
            ) from exc

    def encrypt(self, value: str) -> str:
        if not value:
            raise CredentialEncryptionError(
                "Cannot encrypt an empty credential"
            )

        return self._fernet.encrypt(
            value.encode("utf-8")
        ).decode("utf-8")

    def decrypt(self, value: str) -> str:
        if not value:
            raise CredentialDecryptionError(
                "Cannot decrypt an empty credential"
            )

        try:
            return self._fernet.decrypt(
                value.encode("utf-8")
            ).decode("utf-8")
        except (InvalidToken, ValueError, TypeError) as exc:
            raise CredentialDecryptionError(
                "Unable to decrypt credential"
            ) from exc
