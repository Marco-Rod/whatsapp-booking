from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from test_booking import booking_client  # noqa: F401

from app.core.config import Settings
from app.models import Business, InboundMessage, WhatsAppConnectionStatus
from app.security.credentials import CredentialCipher
from app.services.conversation.result import ConversationResult
from app.services.whatsapp.webhook import WebhookService
from app.services.whatsapp_connection_resolver import (
    WhatsAppConnectionResolver,
)


def payload(
    *,
    phone_number_id: str,
    display_phone_number: str,
    external_message_id: str = "wamid.routing",
) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {
                        "phone_number_id": phone_number_id,
                        "display_phone_number": display_phone_number,
                    },
                    "messages": [{
                        "from": "523312345678",
                        "id": external_message_id,
                        "type": "text",
                        "text": {"body": "hola"},
                    }],
                },
            }],
        }],
    }


class RecordingEngine:
    def __init__(self) -> None:
        self.business_ids: list[int] = []

    async def handle_message_in_transaction(
        self,
        business_id: int,
        phone: str,
        text: str,
    ) -> ConversationResult:
        self.business_ids.append(business_id)
        return ConversationResult(["respuesta"])


def routing_cipher() -> CredentialCipher:
    return CredentialCipher(Fernet.generate_key().decode("utf-8"))


def settings() -> Settings:
    return Settings(
        _env_file=None,
        whatsapp_phone_number_id="legacy-phone",
    )


async def add_connection(
    sessions,
    cipher: CredentialCipher,
    *,
    business_id: int,
    phone_number_id: str,
    status: WhatsAppConnectionStatus = WhatsAppConnectionStatus.CONNECTED,
) -> None:
    async with sessions.begin() as session:
        resolver = WhatsAppConnectionResolver(session, cipher=cipher)
        session.add(
            resolver.create_connection(
                business_id=business_id,
                waba_id="shared-waba",
                phone_number_id=phone_number_id,
                access_token=f"token-{business_id}",
                status=status,
            )
        )


async def process(
    sessions,
    cipher: CredentialCipher,
    webhook_payload: dict,
):
    sender = AsyncMock()
    engine = RecordingEngine()
    async with sessions() as session:
        service = WebhookService(
            session,
            sender,
            settings(),
            engine=engine,
            whatsapp_connection_resolver=WhatsAppConnectionResolver(
                session,
                cipher=cipher,
            ),
        )
        await service.process(webhook_payload)
    return engine, sender


async def test_persisted_phone_number_routes_to_its_business_only(
    booking_client,
):
    _, sessions, _ = booking_client
    cipher = routing_cipher()
    await add_connection(
        sessions,
        cipher,
        business_id=1,
        phone_number_id="phone-a",
    )
    await add_connection(
        sessions,
        cipher,
        business_id=2,
        phone_number_id="phone-b",
    )

    # A signed payload for A carries B's display number. Routing must use only
    # the persisted phone_number_id and therefore remain with Business A.
    engine, sender = await process(
        sessions,
        cipher,
        payload(
            phone_number_id="phone-a",
            display_phone_number="+523300000002",
        ),
    )

    assert engine.business_ids == [1]
    sender.send_for_business.assert_awaited_once_with(1, "+523312345678", "respuesta")
    async with sessions() as session:
        inbound = await session.scalar(select(InboundMessage))
        assert inbound is not None
        assert inbound.business_id == 1


async def test_each_persisted_phone_number_routes_to_its_own_business(
    booking_client,
):
    _, sessions, _ = booking_client
    cipher = routing_cipher()
    await add_connection(sessions, cipher, business_id=1, phone_number_id="phone-a")
    await add_connection(sessions, cipher, business_id=2, phone_number_id="phone-b")

    first, first_sender = await process(
        sessions,
        cipher,
        payload(phone_number_id="phone-a", display_phone_number="+523300000002"),
    )
    second, second_sender = await process(
        sessions,
        cipher,
        payload(
            phone_number_id="phone-b",
            display_phone_number="+523300000001",
            external_message_id="wamid.routing-b",
        ),
    )

    assert first.business_ids == [1]
    assert second.business_ids == [2]
    first_sender.send_for_business.assert_awaited_once_with(1, "+523312345678", "respuesta")
    second_sender.send_for_business.assert_awaited_once_with(2, "+523312345678", "respuesta")


async def test_persisted_connection_takes_priority_over_legacy_phone_id(
    booking_client,
):
    _, sessions, _ = booking_client
    cipher = routing_cipher()
    await add_connection(
        sessions,
        cipher,
        business_id=2,
        phone_number_id="legacy-phone",
    )

    engine, _ = await process(
        sessions,
        cipher,
        payload(
            phone_number_id="legacy-phone",
            display_phone_number="+523300000001",
        ),
    )

    assert engine.business_ids == [2]


@pytest.mark.parametrize(
    "status",
    [
        WhatsAppConnectionStatus.PENDING,
        WhatsAppConnectionStatus.DISCONNECTED,
        WhatsAppConnectionStatus.ERROR,
    ],
)
async def test_inactive_persisted_connection_cannot_fall_back_to_legacy(
    booking_client,
    status,
):
    _, sessions, _ = booking_client
    cipher = routing_cipher()
    await add_connection(
        sessions,
        cipher,
        business_id=2,
        phone_number_id="legacy-phone",
        status=status,
    )

    engine, sender = await process(
        sessions,
        cipher,
        payload(
            phone_number_id="legacy-phone",
            display_phone_number="+523300000001",
        ),
    )

    assert engine.business_ids == []
    sender.send_for_business.assert_not_awaited()
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(InboundMessage)) == 0


async def test_unknown_phone_number_does_not_route_from_display_number(
    booking_client,
):
    _, sessions, _ = booking_client
    engine, sender = await process(
        sessions,
        routing_cipher(),
        payload(
            phone_number_id="unknown-phone",
            display_phone_number="+523300000001",
        ),
    )

    assert engine.business_ids == []
    sender.send_for_business.assert_not_awaited()
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(InboundMessage)) == 0


async def test_legacy_phone_preserves_display_number_routing(
    booking_client,
):
    _, sessions, _ = booking_client
    # The legacy bridge is intentionally the only path that still reads this
    # display number from Business.phone_number.
    async with sessions.begin() as session:
        business = await session.get(Business, 1)
        assert business is not None
        business.phone_number = "+523300000001"

    engine, sender = await process(
        sessions,
        routing_cipher(),
        payload(
            phone_number_id="legacy-phone",
            display_phone_number="+523300000001",
        ),
    )

    assert engine.business_ids == [1]
    sender.send_for_business.assert_awaited_once_with(1, "+523312345678", "respuesta")


async def test_idempotency_remains_scoped_to_routed_business(
    booking_client,
):
    _, sessions, _ = booking_client
    cipher = routing_cipher()
    await add_connection(sessions, cipher, business_id=1, phone_number_id="phone-a")
    await add_connection(sessions, cipher, business_id=2, phone_number_id="phone-b")

    first, _ = await process(
        sessions,
        cipher,
        payload(phone_number_id="phone-a", display_phone_number="+523300000001"),
    )
    second, _ = await process(
        sessions,
        cipher,
        payload(phone_number_id="phone-b", display_phone_number="+523300000002"),
    )

    assert first.business_ids == [1]
    assert second.business_ids == [2]
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(InboundMessage)) == 2
