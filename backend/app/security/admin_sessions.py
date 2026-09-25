import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Business


class AdminSessionError(PermissionError):
    pass


@dataclass(frozen=True)
class AdminSession:
    business_id: int
    credential_version: str
    issued_at: int
    expires_at: int


class AdminSessionManager:
    def __init__(
        self,
        *,
        secret: str,
        max_age_seconds: int = 7 * 24 * 60 * 60,
    ) -> None:
        if not secret:
            raise AdminSessionError(
                "Admin session secret is required"
            )
        if max_age_seconds <= 0:
            raise AdminSessionError(
                "Admin session max age must be positive"
            )

        self._secret = secret.encode("utf-8")
        self.max_age_seconds = max_age_seconds

    def create(
        self,
        *,
        business_id: int,
        admin_token_hash: str,
    ) -> str:
        if business_id <= 0 or not admin_token_hash:
            raise AdminSessionError("Invalid admin session")

        issued_at = int(time.time())
        payload = {
            "business_id": business_id,
            "credential_version": self.credential_version(
                admin_token_hash
            ),
            "iat": issued_at,
            "exp": issued_at + self.max_age_seconds,
        }
        encoded_payload = self._encode_bytes(
            json.dumps(
                payload,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        signature = hmac.new(
            self._secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded_payload}.{self._encode_bytes(signature)}"

    def verify(self, token: str) -> AdminSession:
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
            supplied_signature = self._decode_bytes(encoded_signature)
            expected_signature = hmac.new(
                self._secret,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(
                supplied_signature,
                expected_signature,
            ):
                raise AdminSessionError("Invalid admin session")

            payload = json.loads(
                self._decode_bytes(encoded_payload).decode("utf-8")
            )
            session = AdminSession(
                business_id=int(payload["business_id"]),
                credential_version=str(
                    payload["credential_version"]
                ),
                issued_at=int(payload["iat"]),
                expires_at=int(payload["exp"]),
            )
        except AdminSessionError:
            raise
        except (
            AttributeError,
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ) as exc:
            raise AdminSessionError("Invalid admin session") from exc

        now = int(time.time())
        if (
            session.business_id <= 0
            or not session.credential_version
            or session.issued_at > now + 60
            or session.expires_at <= session.issued_at
            or session.expires_at - session.issued_at
            != self.max_age_seconds
        ):
            raise AdminSessionError("Invalid admin session")
        if now >= session.expires_at:
            raise AdminSessionError("Invalid admin session")
        return session

    def credential_version(self, admin_token_hash: str) -> str:
        if not admin_token_hash:
            raise AdminSessionError("Invalid admin session")
        return hmac.new(
            self._secret,
            f"credential:{admin_token_hash}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _encode_bytes(value: bytes) -> str:
        return (
            base64.urlsafe_b64encode(value)
            .rstrip(b"=")
            .decode("ascii")
        )

    @classmethod
    def _decode_bytes(cls, value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding)
        if cls._encode_bytes(decoded) != value:
            raise AdminSessionError("Invalid admin session")
        return decoded


async def authenticate_admin_session(
    session: AsyncSession,
    token: str,
    manager: AdminSessionManager,
) -> Business:
    signed_session = manager.verify(token)
    business = await session.get(Business, signed_session.business_id)

    if business is None or business.admin_token_hash is None:
        raise AdminSessionError("Invalid admin session")

    expected_version = manager.credential_version(
        business.admin_token_hash
    )
    if not hmac.compare_digest(
        signed_session.credential_version,
        expected_version,
    ):
        raise AdminSessionError("Invalid admin session")

    return business
