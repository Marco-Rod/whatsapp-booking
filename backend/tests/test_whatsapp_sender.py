from cryptography.fernet import Fernet
import pytest

from test_booking import booking_client  # noqa: F401

from app.core.config import Settings
from app.integrations.whatsapp.client import WhatsAppSendError
from app.integrations.whatsapp.reminder_sender import WhatsAppReminderSender
from app.models import WhatsAppConnectionStatus
from app.security.credentials import CredentialCipher
from app.services.whatsapp_connection_resolver import WhatsAppConnectionResolver
from app.services.whatsapp_sender import WhatsAppSender


class RecordingClient:
    def __init__(self, calls, **credentials):
        self.calls = calls
        self.credentials = credentials

    async def send_text(self, recipient, text):
        self.calls.append((self.credentials, recipient, text))


def cipher():
    return CredentialCipher(Fernet.generate_key().decode("utf-8"))


async def add_connection(sessions, secret, *, business_id, phone_number_id, status="connected"):
    async with sessions.begin() as session:
        resolver = WhatsAppConnectionResolver(session, cipher=secret)
        session.add(resolver.create_connection(
            business_id=business_id,
            waba_id="shared-waba",
            phone_number_id=phone_number_id,
            access_token=f"token-{business_id}",
            status=WhatsAppConnectionStatus(status),
        ))


async def test_sender_uses_each_business_persisted_credentials(booking_client):
    _, sessions, _ = booking_client
    secret = cipher()
    await add_connection(sessions, secret, business_id=1, phone_number_id="phone-a")
    await add_connection(sessions, secret, business_id=2, phone_number_id="phone-b")
    calls = []

    def factory(**credentials):
        return RecordingClient(calls, **credentials)

    async with sessions() as session:
        sender = WhatsAppSender(
            session,
            Settings(_env_file=None, whatsapp_api_version="v99.0", whatsapp_legacy_business_id=1),
            resolver=WhatsAppConnectionResolver(session, cipher=secret),
            client_factory=factory,
        )
        await sender.send_for_business(1, "+15555550101", "A")
        await sender.send_for_business(2, "+15555550102", "B")

    assert calls == [
        ({"access_token": "token-1", "phone_number_id": "phone-a", "api_version": "v99.0"}, "+15555550101", "A"),
        ({"access_token": "token-2", "phone_number_id": "phone-b", "api_version": "v99.0"}, "+15555550102", "B"),
    ]


@pytest.mark.parametrize("status", ["pending", "disconnected", "error"])
async def test_inactive_connection_never_falls_back_to_legacy(booking_client, status):
    _, sessions, _ = booking_client
    secret = cipher()
    await add_connection(sessions, secret, business_id=1, phone_number_id="phone-a", status=status)
    calls = []

    async with sessions() as session:
        sender = WhatsAppSender(
            session,
            Settings(_env_file=None, whatsapp_legacy_business_id=1),
            resolver=WhatsAppConnectionResolver(session, cipher=secret),
            client_factory=lambda *args, **kwargs: RecordingClient(calls, **kwargs),
        )
        with pytest.raises(WhatsAppSendError):
            await sender.send_for_business(1, "+15555550101", "blocked")

    assert calls == []


async def test_global_legacy_sender_is_limited_to_explicit_business(booking_client):
    _, sessions, _ = booking_client
    calls = []
    config = Settings(
        _env_file=None,
        whatsapp_legacy_business_id=1,
        whatsapp_access_token="legacy-token",
        whatsapp_phone_number_id="legacy-phone",
        whatsapp_api_version="v99.0",
    )

    def factory(*args, **kwargs):
        assert args == (config,)
        return RecordingClient(calls, legacy=True)

    async with sessions() as session:
        sender = WhatsAppSender(session, config, client_factory=factory)
        await sender.send_for_business(1, "+15555550101", "legacy")
        with pytest.raises(WhatsAppSendError):
            await sender.send_for_business(2, "+15555550102", "must-not-send")

    assert calls == [({"legacy": True}, "+15555550101", "legacy")]


async def test_reminder_adapter_preserves_business_identity(booking_client):
    _, sessions, _ = booking_client
    calls = []

    class Sender:
        async def send_for_business(self, business_id, recipient, text):
            calls.append((business_id, recipient, text))

    reminder_sender = WhatsAppReminderSender(
        sessions,
        Settings(_env_file=None),
        sender_factory=lambda session, config: Sender(),
    )
    await reminder_sender.send_for_business(2, "+15555550102", "Reminder B")

    assert calls == [(2, "+15555550102", "Reminder B")]
