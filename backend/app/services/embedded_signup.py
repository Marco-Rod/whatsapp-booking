from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmbeddedSignupAttempt


class EmbeddedSignupAttemptError(RuntimeError):
    pass


class EmbeddedSignupAttemptNotFoundError(EmbeddedSignupAttemptError):
    pass


class EmbeddedSignupAttemptOwnershipError(EmbeddedSignupAttemptError):
    pass


class EmbeddedSignupAttemptExpiredError(EmbeddedSignupAttemptError):
    pass


class EmbeddedSignupAttemptConsumedError(EmbeddedSignupAttemptError):
    pass


@dataclass(frozen=True)
class CreatedEmbeddedSignupAttempt:
    nonce: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class ValidatedEmbeddedSignupCompletion:
    business_id: int
    authorization_code: str = field(repr=False)
    candidate_account_id: str
    candidate_phone_number_id: str


def hash_attempt_nonce(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive test timestamps without changing PostgreSQL UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class EmbeddedSignupAttemptService:
    """Create and consume application-level signup correlation nonces."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        ttl_seconds: int,
        now=None,
        nonce_factory=secrets.token_urlsafe,
    ) -> None:
        self.session = session
        self.ttl_seconds = ttl_seconds
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.nonce_factory = nonce_factory

    async def start(self, business_id: int) -> CreatedEmbeddedSignupAttempt:
        nonce = self.nonce_factory(32)
        now = self.now()
        expires_at = now + timedelta(seconds=self.ttl_seconds)
        async with self.session.begin():
            attempt = EmbeddedSignupAttempt(
                business_id=business_id,
                nonce_hash=hash_attempt_nonce(nonce),
                expires_at=expires_at,
            )
            self.session.add(attempt)
            await self.session.flush()
        return CreatedEmbeddedSignupAttempt(nonce=nonce, expires_at=expires_at)

    async def complete(
        self,
        *,
        business_id: int,
        attempt_nonce: str,
        authorization_code: str,
        candidate_account_id: str,
        candidate_phone_number_id: str,
    ) -> ValidatedEmbeddedSignupCompletion:
        nonce_hash = hash_attempt_nonce(attempt_nonce)
        now = self.now()
        database_now = now
        if self.session.bind and self.session.bind.dialect.name == "sqlite":
            database_now = now.replace(tzinfo=None)
        async with self.session.begin():
            attempt = await self.session.scalar(
                select(EmbeddedSignupAttempt).where(
                    EmbeddedSignupAttempt.nonce_hash == nonce_hash
                )
            )
            if attempt is None:
                raise EmbeddedSignupAttemptNotFoundError("Invalid signup attempt")
            if attempt.business_id != business_id:
                raise EmbeddedSignupAttemptOwnershipError("Signup attempt does not belong to this business")
            if _as_utc(attempt.expires_at) <= now:
                raise EmbeddedSignupAttemptExpiredError("Signup attempt has expired")
            if attempt.consumed_at is not None:
                raise EmbeddedSignupAttemptConsumedError("Signup attempt was already consumed")

            consumed = await self.session.execute(
                update(EmbeddedSignupAttempt)
                .where(
                    EmbeddedSignupAttempt.id == attempt.id,
                    EmbeddedSignupAttempt.business_id == business_id,
                    EmbeddedSignupAttempt.consumed_at.is_(None),
                    EmbeddedSignupAttempt.expires_at > database_now,
                )
                .values(consumed_at=database_now)
            )
            if consumed.rowcount != 1:
                raise EmbeddedSignupAttemptConsumedError("Signup attempt was already consumed")

        return ValidatedEmbeddedSignupCompletion(
            business_id=business_id,
            authorization_code=authorization_code,
            candidate_account_id=candidate_account_id,
            candidate_phone_number_id=candidate_phone_number_id,
        )
