"""Explicit, one-time migration of legacy WhatsApp credentials for one business."""

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.models import Business, WhatsAppConnection, WhatsAppConnectionStatus
from app.security.credentials import CredentialEncryptionError
from app.security.factory import build_credential_cipher
from app.services.whatsapp_connection_resolver import WhatsAppConnectionResolver


class BackfillError(RuntimeError):
    """A safe operational error that never embeds provider credentials."""


class BackfillConfigurationError(BackfillError):
    pass


class BackfillConflictError(BackfillError):
    pass


class BackfillBusinessNotFoundError(BackfillError):
    pass


@dataclass(frozen=True)
class BackfillResult:
    action: str
    business_id: int
    phone_number_id: str
    status: str
    connection_id: int | None = None


def _legacy_credentials(config: Settings) -> tuple[str, str, str]:
    """Return only complete legacy values; never include them in an error."""
    access_token = config.whatsapp_access_token.get_secret_value()
    phone_number_id = config.whatsapp_phone_number_id.strip()
    waba_id = config.whatsapp_waba_id.strip()
    if not access_token:
        raise BackfillConfigurationError("WhatsApp access token is not configured")
    if not phone_number_id:
        raise BackfillConfigurationError("WhatsApp phone number ID is not configured")
    if not waba_id:
        raise BackfillConfigurationError("WhatsApp WABA ID is not configured")
    return access_token, phone_number_id, waba_id


async def backfill_whatsapp_connection(
    session: AsyncSession,
    *,
    business_id: int,
    config: Settings,
    dry_run: bool = False,
) -> BackfillResult:
    """Create one connected link from legacy env credentials without updating links."""
    if business_id <= 0:
        raise ValueError("business_id must be positive")

    access_token, phone_number_id, waba_id = _legacy_credentials(config)
    try:
        cipher = build_credential_cipher(config)
    except CredentialEncryptionError as exc:
        raise BackfillConfigurationError("Credential encryption is unavailable") from exc

    async with session.begin():
        business = await session.scalar(
            select(Business)
            .where(Business.id == business_id)
            .with_for_update()
        )
        if business is None:
            raise BackfillBusinessNotFoundError("Business not found")

        existing_for_business = await session.scalar(
            select(WhatsAppConnection)
            .where(WhatsAppConnection.business_id == business_id)
            .with_for_update()
        )
        existing_for_phone = await session.scalar(
            select(WhatsAppConnection)
            .where(WhatsAppConnection.phone_number_id == phone_number_id)
            .with_for_update()
        )

        if existing_for_business is not None:
            if existing_for_business.phone_number_id != phone_number_id:
                raise BackfillConflictError(
                    "Business already has a different WhatsApp connection"
                )
            if existing_for_business.status != WhatsAppConnectionStatus.CONNECTED.value:
                raise BackfillConflictError(
                    "Business has an inactive WhatsApp connection"
                )
            if existing_for_business.waba_id != waba_id:
                raise BackfillConflictError(
                    "Business connection does not match the configured WABA"
                )
            return BackfillResult(
                action="already_migrated",
                business_id=business_id,
                connection_id=existing_for_business.id,
                phone_number_id=phone_number_id,
                status=existing_for_business.status,
            )

        if existing_for_phone is not None:
            raise BackfillConflictError(
                "Configured phone number ID belongs to another business"
            )

        if dry_run:
            return BackfillResult(
                action="would_migrate",
                business_id=business_id,
                phone_number_id=phone_number_id,
                status=WhatsAppConnectionStatus.CONNECTED.value,
            )

        connection = WhatsAppConnectionResolver(
            session,
            cipher=cipher,
        ).create_connection(
            business_id=business_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            access_token=access_token,
            status=WhatsAppConnectionStatus.CONNECTED,
            connected_at=datetime.now(timezone.utc),
        )
        session.add(connection)
        await session.flush()
        return BackfillResult(
            action="created",
            business_id=business_id,
            connection_id=connection.id,
            phone_number_id=phone_number_id,
            status=connection.status,
        )


async def run(
    business_id: int,
    *,
    dry_run: bool = False,
) -> BackfillResult:
    config = Settings()
    engine = create_async_engine(config.database_url)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            return await backfill_whatsapp_connection(
                session,
                business_id=business_id,
                config=config,
                dry_run=dry_run,
            )
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill one legacy WhatsApp connection from environment configuration."
    )
    parser.add_argument(
        "--business-id",
        type=int,
        required=True,
        help="Explicit business to migrate",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without creating a connection",
    )
    args = parser.parse_args(argv)
    if args.business_id <= 0:
        parser.error("--business-id must be positive")

    try:
        result = asyncio.run(run(args.business_id, dry_run=args.dry_run))
    except KeyboardInterrupt:
        print("WhatsApp connection backfill interrupted", file=sys.stderr)
        return 130
    except BackfillConfigurationError:
        print(
            "WhatsApp connection backfill failed: configuration is incomplete or invalid",
            file=sys.stderr,
        )
        return 2
    except BackfillBusinessNotFoundError:
        print("WhatsApp connection backfill failed: business not found", file=sys.stderr)
        return 2
    except BackfillConflictError:
        print("WhatsApp connection backfill failed: connection conflict", file=sys.stderr)
        return 2
    except Exception as exc:
        # Never render third-party, database, or configuration exception text.
        print(
            "WhatsApp connection backfill failed: "
            f"error={type(exc).__name__}",
            file=sys.stderr,
        )
        return 2

    print(
        "WhatsApp connection backfill "
        f"{result.action}: business_id={result.business_id} "
        f"connection_id={result.connection_id} "
        f"phone_number_id={result.phone_number_id} status={result.status}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
