from sqlalchemy import event, func, select
import pytest
from cryptography.fernet import Fernet

from test_booking import booking_client  # noqa: F401

from app.commands import backfill_whatsapp_connection as command
from app.core.config import Settings
from app.models import WhatsAppConnection, WhatsAppConnectionStatus
from app.security.credentials import CredentialCipher
from app.services.whatsapp_connection_resolver import WhatsAppConnectionResolver


TOKEN = "legacy-access-token-that-must-never-be-printed"
PHONE_NUMBER_ID = "legacy-phone-number-id"
WABA_ID = "legacy-waba-id"


def config(**overrides) -> Settings:
    values = {
        "whatsapp_access_token": TOKEN,
        "whatsapp_phone_number_id": PHONE_NUMBER_ID,
        "whatsapp_waba_id": WABA_ID,
        "credential_encryption_key": Fernet.generate_key().decode("utf-8"),
        **overrides,
    }
    return Settings(
        _env_file=None,
        **values,
    )


async def count_connections(sessions) -> int:
    async with sessions() as session:
        return await session.scalar(select(func.count()).select_from(WhatsAppConnection))


async def create_connection(
    sessions,
    *,
    business_id: int,
    phone_number_id: str,
    waba_id: str = WABA_ID,
    status: WhatsAppConnectionStatus = WhatsAppConnectionStatus.CONNECTED,
):
    async with sessions.begin() as session:
        resolver = WhatsAppConnectionResolver(
            session,
            cipher=CredentialCipher(Fernet.generate_key().decode("utf-8")),
        )
        connection = resolver.create_connection(
            business_id=business_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            access_token="existing-token",
            status=status,
        )
        session.add(connection)
        await session.flush()
        return connection.id


async def run_backfill(sessions, *, business_id=1, settings=None, dry_run=False):
    async with sessions() as session:
        return await command.backfill_whatsapp_connection(
            session,
            business_id=business_id,
            config=settings or config(),
            dry_run=dry_run,
        )


async def test_backfill_creates_encrypted_connected_connection_and_resolves_token(
    booking_client,
):
    _, sessions, _ = booking_client
    settings = config()

    result = await run_backfill(sessions, settings=settings)

    assert result.action == "created"
    assert result.business_id == 1
    assert result.status == WhatsAppConnectionStatus.CONNECTED.value
    assert result.connection_id is not None
    async with sessions() as session:
        stored = await session.get(WhatsAppConnection, result.connection_id)
        assert stored is not None
        assert stored.encrypted_access_token != TOKEN
        assert TOKEN not in stored.encrypted_access_token
        assert stored.phone_number_id == PHONE_NUMBER_ID
        assert stored.waba_id == WABA_ID
        assert stored.status == WhatsAppConnectionStatus.CONNECTED.value
        resolved = await WhatsAppConnectionResolver(
            session,
            cipher=CredentialCipher(settings.credential_encryption_key.get_secret_value()),
        ).resolve_for_business(1)
        assert resolved is not None
        assert resolved.access_token == TOKEN


async def test_backfill_is_idempotent_for_same_connected_phone_and_waba(booking_client):
    _, sessions, _ = booking_client
    settings = config()
    first = await run_backfill(sessions, settings=settings)
    async with sessions() as session:
        encrypted_before = (await session.get(WhatsAppConnection, first.connection_id)).encrypted_access_token

    second = await run_backfill(sessions, settings=settings)

    assert second.action == "already_migrated"
    assert second.connection_id == first.connection_id
    assert await count_connections(sessions) == 1
    async with sessions() as session:
        stored = await session.get(WhatsAppConnection, first.connection_id)
        assert stored.encrypted_access_token == encrypted_before


async def test_backfill_dry_run_validates_without_writing(booking_client):
    _, sessions, _ = booking_client

    result = await run_backfill(sessions, dry_run=True)

    assert result.action == "would_migrate"
    assert result.connection_id is None
    assert await count_connections(sessions) == 0


async def test_backfill_rejects_unknown_business_without_writing(booking_client):
    _, sessions, _ = booking_client

    with pytest.raises(command.BackfillBusinessNotFoundError):
        await run_backfill(sessions, business_id=999)

    assert await count_connections(sessions) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"whatsapp_access_token": ""},
        {"whatsapp_phone_number_id": ""},
        {"whatsapp_waba_id": ""},
        {"credential_encryption_key": None},
        {"credential_encryption_key": "not-a-fernet-key"},
    ],
)
async def test_backfill_rejects_incomplete_or_invalid_configuration_without_writing(
    booking_client,
    overrides,
):
    _, sessions, _ = booking_client

    with pytest.raises(command.BackfillConfigurationError):
        await run_backfill(sessions, settings=config(**overrides))

    assert await count_connections(sessions) == 0


async def test_backfill_rejects_business_with_another_phone_without_writing(booking_client):
    _, sessions, _ = booking_client
    await create_connection(sessions, business_id=1, phone_number_id="other-phone")

    with pytest.raises(command.BackfillConflictError):
        await run_backfill(sessions)

    assert await count_connections(sessions) == 1


async def test_backfill_rejects_phone_owned_by_another_business_without_writing(booking_client):
    _, sessions, _ = booking_client
    await create_connection(sessions, business_id=2, phone_number_id=PHONE_NUMBER_ID)

    with pytest.raises(command.BackfillConflictError):
        await run_backfill(sessions)

    assert await count_connections(sessions) == 1


async def test_backfill_rejects_same_phone_with_a_different_waba_without_writing(
    booking_client,
):
    _, sessions, _ = booking_client
    await create_connection(
        sessions,
        business_id=1,
        phone_number_id=PHONE_NUMBER_ID,
        waba_id="other-waba",
    )

    with pytest.raises(command.BackfillConflictError):
        await run_backfill(sessions)

    assert await count_connections(sessions) == 1


@pytest.mark.parametrize(
    "status",
    [
        WhatsAppConnectionStatus.PENDING,
        WhatsAppConnectionStatus.DISCONNECTED,
        WhatsAppConnectionStatus.ERROR,
    ],
)
async def test_backfill_never_reactivates_inactive_connection(booking_client, status):
    _, sessions, _ = booking_client
    await create_connection(
        sessions,
        business_id=1,
        phone_number_id=PHONE_NUMBER_ID,
        status=status,
    )

    with pytest.raises(command.BackfillConflictError):
        await run_backfill(sessions)

    async with sessions() as session:
        stored = await session.scalar(select(WhatsAppConnection))
        assert stored.status == status.value


async def test_backfill_rolls_back_when_creation_flush_fails(booking_client):
    _, sessions, _ = booking_client
    async with sessions() as session:
        def fail_flush(*_args, **_kwargs):
            raise RuntimeError("simulated write failure")

        event.listen(session.sync_session, "before_flush", fail_flush)
        try:
            with pytest.raises(RuntimeError):
                await command.backfill_whatsapp_connection(
                    session,
                    business_id=1,
                    config=config(),
                )
        finally:
            event.remove(session.sync_session, "before_flush", fail_flush)

    assert await count_connections(sessions) == 0


def test_cli_requires_explicit_business_id():
    with pytest.raises(SystemExit) as error:
        command.main([])

    assert error.value.code == 2


def test_cli_never_prints_plaintext_token_on_unexpected_failure(monkeypatch, capsys):
    async def fail(*_args, **_kwargs):
        raise RuntimeError(TOKEN)

    monkeypatch.setattr(command, "run", fail)

    assert command.main(["--business-id", "1"]) == 2

    output = capsys.readouterr()
    assert TOKEN not in output.out
    assert TOKEN not in output.err


def test_cli_never_prints_plaintext_token_from_safe_command_error(monkeypatch, capsys):
    async def fail(*_args, **_kwargs):
        raise command.BackfillConflictError(TOKEN)

    monkeypatch.setattr(command, "run", fail)

    assert command.main(["--business-id", "1"]) == 2

    output = capsys.readouterr()
    assert TOKEN not in output.out
    assert TOKEN not in output.err


def test_cli_never_prints_plaintext_token_on_success(monkeypatch, capsys):
    async def succeed(*_args, **_kwargs):
        return command.BackfillResult(
            action="created",
            business_id=1,
            connection_id=7,
            phone_number_id=PHONE_NUMBER_ID,
            status="connected",
        )

    monkeypatch.setattr(command, "run", succeed)

    assert command.main(["--business-id", "1"]) == 0

    output = capsys.readouterr()
    assert TOKEN not in output.out
    assert TOKEN not in output.err
