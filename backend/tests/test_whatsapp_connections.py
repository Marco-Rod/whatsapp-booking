from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError

from test_booking import booking_client  # noqa: F401

from app.api.v1.google_integrations import GoogleIntegrationStatus
from app.models import WhatsAppConnection, WhatsAppConnectionStatus
from app.repositories.whatsapp_connections import WhatsAppConnectionRepository
from app.security.credentials import CredentialCipher
from app.services.whatsapp_connection_resolver import (
    WhatsAppConnectionResolver,
)


@pytest.fixture
def cipher() -> CredentialCipher:
    return CredentialCipher(Fernet.generate_key().decode("utf-8"))


def connection(
    resolver: WhatsAppConnectionResolver,
    *,
    business_id: int,
    waba_id: str,
    phone_number_id: str,
    access_token: str,
    status: WhatsAppConnectionStatus = WhatsAppConnectionStatus.CONNECTED,
) -> WhatsAppConnection:
    return resolver.create_connection(
        business_id=business_id,
        waba_id=waba_id,
        phone_number_id=phone_number_id,
        display_phone_number=f"+5233000{business_id:04d}",
        access_token=access_token,
        granted_scopes=["whatsapp_business_messaging"],
        status=status,
        connected_at=datetime(2026, 9, 28, tzinfo=timezone.utc),
    )


async def test_connection_is_encrypted_and_resolves_per_business(
    booking_client,
    cipher,
):
    _, sessions, _ = booking_client
    async with sessions.begin() as session:
        resolver = WhatsAppConnectionResolver(session, cipher=cipher)
        first = connection(
            resolver,
            business_id=1,
            waba_id="shared-waba",
            phone_number_id="phone-a",
            access_token="access-token-a",
        )
        second = connection(
            resolver,
            business_id=2,
            waba_id="shared-waba",
            phone_number_id="phone-b",
            access_token="access-token-b",
        )
        session.add_all([first, second])
        await session.flush()

        assert first.encrypted_access_token != "access-token-a"
        assert "access-token-a" not in repr(first)

    async with sessions() as session:
        resolver = WhatsAppConnectionResolver(session, cipher=cipher)
        for phone_number_id, business_id, token in (
            ("phone-a", 1, "access-token-a"),
            ("phone-b", 2, "access-token-b"),
        ):
            resolved = await resolver.resolve_from_phone_number_id(
                phone_number_id
            )
            assert resolved is not None
            assert resolved.business_id == business_id
            assert resolved.phone_number_id == phone_number_id
            assert resolved.access_token == token
            assert token not in repr(resolved)


async def test_repository_looks_up_business_and_phone_number_id(
    booking_client,
    cipher,
):
    _, sessions, _ = booking_client
    async with sessions.begin() as session:
        resolver = WhatsAppConnectionResolver(session, cipher=cipher)
        session.add(
            connection(
                resolver,
                business_id=1,
                waba_id="waba-a",
                phone_number_id="phone-a",
                access_token="access-token-a",
            )
        )

    async with sessions() as session:
        repository = WhatsAppConnectionRepository(session)
        by_business = await repository.get_by_business_id(1)
        by_phone = await repository.get_by_phone_number_id("phone-a")

        assert by_business is not None
        assert by_phone is not None
        assert by_business.id == by_phone.id
        assert await repository.get_by_business_id(999) is None
        assert await repository.get_by_phone_number_id("unknown") is None


async def test_unknown_connection_does_not_require_credential_configuration(
    booking_client,
):
    _, sessions, _ = booking_client
    async with sessions() as session:
        resolver = WhatsAppConnectionResolver(session)

        assert await resolver.resolve_for_business(999) is None
        assert await resolver.resolve_from_phone_number_id("unknown") is None


async def test_connected_resolver_excludes_pending_and_disconnected_connections(
    booking_client,
    cipher,
):
    _, sessions, _ = booking_client
    async with sessions.begin() as session:
        resolver = WhatsAppConnectionResolver(session, cipher=cipher)
        pending = connection(
            resolver,
            business_id=1,
            waba_id="waba-a",
            phone_number_id="phone-a",
            access_token="access-token-a",
            status=WhatsAppConnectionStatus.PENDING,
        )
        session.add(pending)

    async with sessions() as session:
        resolver = WhatsAppConnectionResolver(session, cipher=cipher)
        assert await resolver.resolve_for_business(1) is None

    async with sessions.begin() as session:
        stored = await session.get(WhatsAppConnection, 1)
        assert stored is not None
        stored.status = WhatsAppConnectionStatus.CONNECTED.value

    async with sessions() as session:
        resolver = WhatsAppConnectionResolver(session, cipher=cipher)
        resolved = await resolver.resolve_for_business(1)
        assert resolved is not None
        assert resolved.access_token == "access-token-a"

    async with sessions.begin() as session:
        stored = await session.get(WhatsAppConnection, 1)
        assert stored is not None
        stored.status = WhatsAppConnectionStatus.DISCONNECTED.value

    async with sessions() as session:
        resolver = WhatsAppConnectionResolver(session, cipher=cipher)
        assert await resolver.resolve_for_business(1) is None


@pytest.mark.parametrize(
    "duplicate",
    ["business_id", "phone_number_id"],
)
async def test_connection_identifiers_are_unique(
    booking_client,
    cipher,
    duplicate,
):
    _, sessions, _ = booking_client
    async with sessions.begin() as session:
        resolver = WhatsAppConnectionResolver(session, cipher=cipher)
        session.add(
            connection(
                resolver,
                business_id=1,
                waba_id="waba-a",
                phone_number_id="phone-a",
                access_token="access-token-a",
            )
        )

    with pytest.raises(IntegrityError):
        async with sessions.begin() as session:
            resolver = WhatsAppConnectionResolver(session, cipher=cipher)
            session.add(
                connection(
                    resolver,
                    business_id=1 if duplicate == "business_id" else 2,
                    waba_id="waba-b",
                    phone_number_id=(
                        "phone-b"
                        if duplicate == "business_id"
                        else "phone-a"
                    ),
                    access_token="access-token-b",
                )
            )


def test_existing_administrative_dtos_do_not_expose_provider_credentials():
    assert "access_token" not in GoogleIntegrationStatus.model_fields
    assert "encrypted_access_token" not in GoogleIntegrationStatus.model_fields
