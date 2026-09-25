import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import time


class OAuthStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class OAuthState:
    business_id: int
    code_verifier: str


class OAuthStateManager:
    def __init__(
        self,
        *,
        secret: str,
        max_age_seconds: int = 600,
    ) -> None:
        if not secret:
            raise OAuthStateError("OAuth state secret is required")

        if max_age_seconds <= 0:
            raise OAuthStateError(
                "OAuth state max age must be positive"
            )

        self._secret = secret.encode("utf-8")
        self._max_age_seconds = max_age_seconds

    def create(
        self,
        *,
        business_id: int,
        code_verifier: str,
    ) -> str:
        if business_id <= 0:
            raise OAuthStateError(
                "Business id must be positive"
            )

        if not code_verifier:
            raise OAuthStateError(
                "OAuth code verifier is required"
            )

        payload = {
            "business_id": business_id,
            "code_verifier": code_verifier,
            "issued_at": int(time.time()),
        }

        encoded_payload = self._encode_payload(payload)

        signature = hmac.new(
            self._secret,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()

        return (
            f"{encoded_payload}."
            f"{self._encode_bytes(signature)}"
        )

    def verify(self, state: str) -> OAuthState:
        try:
            encoded_payload, encoded_signature = state.split(".", 1)

            supplied_signature = self._decode_bytes(
                encoded_signature
            )

            expected_signature = hmac.new(
                self._secret,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()

            if not hmac.compare_digest(
                supplied_signature,
                expected_signature,
            ):
                raise OAuthStateError(
                    "Invalid OAuth state"
                )

            payload = json.loads(
                self._decode_bytes(
                    encoded_payload
                ).decode("utf-8")
            )

            business_id = int(payload["business_id"])
            code_verifier = str(payload["code_verifier"])
            issued_at = int(payload["issued_at"])

        except OAuthStateError:
            raise
        except (
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
        ) as exc:
            raise OAuthStateError(
                "Invalid OAuth state"
            ) from exc

        if business_id <= 0:
            raise OAuthStateError(
                "Invalid OAuth state"
            )

        if not code_verifier:
            raise OAuthStateError(
                "Invalid OAuth state"
            )

        now = int(time.time())

        if issued_at > now + 60:
            raise OAuthStateError(
                "Invalid OAuth state"
            )

        if now - issued_at > self._max_age_seconds:
            raise OAuthStateError(
                "OAuth state has expired"
            )

        return OAuthState(
            business_id=business_id,
            code_verifier=code_verifier,
        )

    @staticmethod
    def _encode_payload(payload: dict) -> str:
        raw = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        return OAuthStateManager._encode_bytes(raw)

    @staticmethod
    def _encode_bytes(value: bytes) -> str:
        return (
            base64.urlsafe_b64encode(value)
            .rstrip(b"=")
            .decode("ascii")
        )

    @staticmethod
    def _decode_bytes(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(value + padding)

        if OAuthStateManager._encode_bytes(decoded) != value:
            raise OAuthStateError("Invalid OAuth state")

        return decoded
