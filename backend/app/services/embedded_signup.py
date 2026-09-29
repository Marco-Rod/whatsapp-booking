from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmbeddedSignupAttempt, EmbeddedSignupAttemptStatus


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


class EmbeddedSignupAttemptLeaseError(EmbeddedSignupAttemptError):
    pass


class EmbeddedSignupAttemptProcessingError(EmbeddedSignupAttemptError):
    pass


@dataclass(frozen=True)
class CreatedEmbeddedSignupAttempt:
    nonce: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class AcquiredEmbeddedSignupAttempt:
    attempt_id: int
    business_id: int
    expires_at: datetime
    processing_expires_at: datetime
    lease_token: str = field(repr=False)


def hash_attempt_nonce(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def hash_processing_lease(lease_token: str) -> str:
    return hashlib.sha256(lease_token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive test timestamps without changing PostgreSQL UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class EmbeddedSignupAttemptService:
    """Manage short-lived application leases without holding DB work across I/O."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        ttl_seconds: int,
        processing_lease_seconds: int,
        now=None,
        nonce_factory=secrets.token_urlsafe,
        lease_factory=secrets.token_urlsafe,
    ) -> None:
        self.session = session
        self.ttl_seconds = ttl_seconds
        self.processing_lease_seconds = processing_lease_seconds
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.nonce_factory = nonce_factory
        self.lease_factory = lease_factory

    def _database_time(self, now: datetime) -> datetime:
        if self.session.bind and self.session.bind.dialect.name == "sqlite":
            return now.replace(tzinfo=None)
        return now

    async def start(self, business_id: int) -> CreatedEmbeddedSignupAttempt:
        nonce = self.nonce_factory(32)
        now = self.now()
        expires_at = now + timedelta(seconds=self.ttl_seconds)
        async with self.session.begin():
            self.session.add(
                EmbeddedSignupAttempt(
                    business_id=business_id,
                    nonce_hash=hash_attempt_nonce(nonce),
                    expires_at=expires_at,
                    status=EmbeddedSignupAttemptStatus.READY.value,
                )
            )
            await self.session.flush()
        return CreatedEmbeddedSignupAttempt(nonce=nonce, expires_at=expires_at)

    async def acquire(
        self,
        *,
        business_id: int,
        attempt_nonce: str,
    ) -> AcquiredEmbeddedSignupAttempt:
        now = self.now()
        database_now = self._database_time(now)
        nonce_hash = hash_attempt_nonce(attempt_nonce)
        lease_token = self.lease_factory(32)
        lease_hash = hash_processing_lease(lease_token)

        async with self.session.begin():
            attempt = await self._get_for_validation(nonce_hash)
            self._validate_owner_and_lifetime(attempt, business_id, now)
            if (
                attempt.status == EmbeddedSignupAttemptStatus.PROCESSING.value
                and _as_utc(attempt.processing_expires_at) > now
            ):
                raise EmbeddedSignupAttemptProcessingError("Signup attempt is processing")

            processing_expires_at = min(
                _as_utc(attempt.expires_at),
                now + timedelta(seconds=self.processing_lease_seconds),
            )
            stored_processing_expiry = self._database_time(processing_expires_at)
            acquired = await self.session.execute(
                update(EmbeddedSignupAttempt)
                .where(
                    EmbeddedSignupAttempt.id == attempt.id,
                    EmbeddedSignupAttempt.business_id == business_id,
                    EmbeddedSignupAttempt.consumed_at.is_(None),
                    EmbeddedSignupAttempt.expires_at > database_now,
                    or_(
                        EmbeddedSignupAttempt.status
                        == EmbeddedSignupAttemptStatus.READY.value,
                        and_(
                            EmbeddedSignupAttempt.status
                            == EmbeddedSignupAttemptStatus.PROCESSING.value,
                            EmbeddedSignupAttempt.processing_expires_at <= database_now,
                        ),
                    ),
                )
                .values(
                    status=EmbeddedSignupAttemptStatus.PROCESSING.value,
                    processing_started_at=database_now,
                    processing_expires_at=stored_processing_expiry,
                    processing_lease_hash=lease_hash,
                )
            )
            if acquired.rowcount != 1:
                raise EmbeddedSignupAttemptProcessingError("Signup attempt is processing")

        return AcquiredEmbeddedSignupAttempt(
            attempt_id=attempt.id,
            business_id=business_id,
            expires_at=_as_utc(attempt.expires_at),
            processing_expires_at=processing_expires_at,
            lease_token=lease_token,
        )

    async def finalize_success(
        self,
        *,
        business_id: int,
        attempt_id: int,
        lease_token: str,
    ) -> None:
        async with self.session.begin():
            await self.finalize_success_in_transaction(
                business_id=business_id,
                attempt_id=attempt_id,
                lease_token=lease_token,
            )

    async def finalize_success_in_transaction(
        self,
        *,
        business_id: int,
        attempt_id: int,
        lease_token: str,
    ) -> None:
        now = self.now()
        database_now = self._database_time(now)
        finalized = await self.session.execute(
            update(EmbeddedSignupAttempt)
            .where(
                EmbeddedSignupAttempt.id == attempt_id,
                EmbeddedSignupAttempt.business_id == business_id,
                EmbeddedSignupAttempt.status
                == EmbeddedSignupAttemptStatus.PROCESSING.value,
                EmbeddedSignupAttempt.processing_lease_hash
                == hash_processing_lease(lease_token),
                EmbeddedSignupAttempt.processing_expires_at > database_now,
                EmbeddedSignupAttempt.expires_at > database_now,
                EmbeddedSignupAttempt.consumed_at.is_(None),
            )
            .values(
                status=EmbeddedSignupAttemptStatus.CONSUMED.value,
                consumed_at=database_now,
                processing_started_at=None,
                processing_expires_at=None,
                processing_lease_hash=None,
            )
        )
        if finalized.rowcount != 1:
            await self._raise_finalize_or_release_error(
                business_id=business_id,
                attempt_id=attempt_id,
                now=now,
            )

    async def release(
        self,
        *,
        business_id: int,
        attempt_id: int,
        lease_token: str,
    ) -> None:
        async with self.session.begin():
            await self.release_in_transaction(
                business_id=business_id,
                attempt_id=attempt_id,
                lease_token=lease_token,
            )

    async def release_in_transaction(
        self,
        *,
        business_id: int,
        attempt_id: int,
        lease_token: str,
    ) -> None:
        now = self.now()
        database_now = self._database_time(now)
        released = await self.session.execute(
            update(EmbeddedSignupAttempt)
            .where(
                EmbeddedSignupAttempt.id == attempt_id,
                EmbeddedSignupAttempt.business_id == business_id,
                EmbeddedSignupAttempt.status
                == EmbeddedSignupAttemptStatus.PROCESSING.value,
                EmbeddedSignupAttempt.processing_lease_hash
                == hash_processing_lease(lease_token),
                EmbeddedSignupAttempt.processing_expires_at > database_now,
                EmbeddedSignupAttempt.expires_at > database_now,
                EmbeddedSignupAttempt.consumed_at.is_(None),
            )
            .values(
                status=EmbeddedSignupAttemptStatus.READY.value,
                processing_started_at=None,
                processing_expires_at=None,
                processing_lease_hash=None,
            )
        )
        if released.rowcount != 1:
            await self._raise_finalize_or_release_error(
                business_id=business_id,
                attempt_id=attempt_id,
                now=now,
            )

    async def _get_for_validation(self, nonce_hash: str) -> EmbeddedSignupAttempt:
        attempt = await self.session.scalar(
            select(EmbeddedSignupAttempt).where(
                EmbeddedSignupAttempt.nonce_hash == nonce_hash
            )
        )
        if attempt is None:
            raise EmbeddedSignupAttemptNotFoundError("Invalid signup attempt")
        return attempt

    def _validate_owner_and_lifetime(
        self,
        attempt: EmbeddedSignupAttempt,
        business_id: int,
        now: datetime,
    ) -> None:
        if attempt.business_id != business_id:
            raise EmbeddedSignupAttemptOwnershipError("Signup attempt does not belong to this business")
        if _as_utc(attempt.expires_at) <= now:
            raise EmbeddedSignupAttemptExpiredError("Signup attempt has expired")
        if (
            attempt.status == EmbeddedSignupAttemptStatus.CONSUMED.value
            or attempt.consumed_at is not None
        ):
            raise EmbeddedSignupAttemptConsumedError("Signup attempt was already consumed")

    async def _raise_finalize_or_release_error(
        self,
        *,
        business_id: int,
        attempt_id: int,
        now: datetime,
    ) -> None:
        attempt = await self.session.get(EmbeddedSignupAttempt, attempt_id)
        if attempt is None:
            raise EmbeddedSignupAttemptNotFoundError("Invalid signup attempt")
        self._validate_owner_and_lifetime(attempt, business_id, now)
        raise EmbeddedSignupAttemptLeaseError("Signup attempt lease is no longer valid")
