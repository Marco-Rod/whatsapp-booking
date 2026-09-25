import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import time
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.id_token import verify_oauth2_token


class GoogleIdentityError(PermissionError):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    display_name: str | None
    email_verified: bool


class GoogleIdentityVerifier:
    _VALID_ISSUERS = {
        "accounts.google.com",
        "https://accounts.google.com",
    }

    def __init__(
        self,
        *,
        client_id: str,
        token_verifier: Callable[..., Mapping[str, Any]] = (
            verify_oauth2_token
        ),
        request_factory: Callable[[], Any] = Request,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not client_id:
            raise GoogleIdentityError("Invalid Google identity")

        self._client_id = client_id
        self._token_verifier = token_verifier
        self._request_factory = request_factory
        self._clock = clock

    async def verify(self, credential: str) -> GoogleIdentity:
        if not credential:
            raise GoogleIdentityError("Invalid Google identity")

        try:
            claims = await asyncio.to_thread(
                self._token_verifier,
                credential,
                self._request_factory(),
                self._client_id,
            )
            return self._identity_from_claims(claims)
        except GoogleIdentityError:
            raise
        except Exception as exc:
            raise GoogleIdentityError(
                "Invalid Google identity"
            ) from exc

    def _identity_from_claims(
        self,
        claims: Mapping[str, Any],
    ) -> GoogleIdentity:
        try:
            audience = claims["aud"]
            issuer = claims["iss"]
            expires_at = int(claims["exp"])
            subject = claims["sub"]
            email = claims["email"]
            email_verified = claims["email_verified"]
        except (KeyError, TypeError, ValueError) as exc:
            raise GoogleIdentityError(
                "Invalid Google identity"
            ) from exc

        if audience != self._client_id:
            raise GoogleIdentityError("Invalid Google identity")
        if issuer not in self._VALID_ISSUERS:
            raise GoogleIdentityError("Invalid Google identity")
        if expires_at <= int(self._clock()):
            raise GoogleIdentityError("Invalid Google identity")
        if not isinstance(subject, str) or not subject.strip():
            raise GoogleIdentityError("Invalid Google identity")
        if not isinstance(email, str) or not email.strip():
            raise GoogleIdentityError("Invalid Google identity")
        if email_verified is not True:
            raise GoogleIdentityError("Invalid Google identity")

        display_name = claims.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = None
        else:
            display_name = display_name.strip()

        return GoogleIdentity(
            subject=subject.strip(),
            email=email.strip(),
            display_name=display_name,
            email_verified=True,
        )
