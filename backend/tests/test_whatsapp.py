import asyncio
import hashlib
import hmac
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends
from sqlalchemy import func, select

from test_booking import booking_client
from test_conversation_engine import NOW
from app.api.v1.whatsapp import get_webhook_service, get_whatsapp_settings
from app.core.config import Settings
from app.core.database import get_session
from app.integrations.whatsapp.client import WhatsAppClient, WhatsAppSendError
from app.integrations.whatsapp.parser import parse_messages
from app.main import app
from app.models import Appointment, Business, Conversation, InboundMessage
from app.services.conversation.engine import ConversationEngine
from app.services.whatsapp.webhook import WebhookService
from app.services.calendar import CalendarService
from app.integrations.google_calendar.errors import GoogleCalendarError

URL = "/api/v1/webhooks/whatsapp"


def envelope(text="hola", message_id="wamid.test"):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages",
        "value": {"metadata": {"phone_number_id": "123456", "display_phone_number": "52 33 0000 0001"},
                  "messages": [{"from": "523312345678", "id": message_id, "type": "text", "text": {"body": text}}]}}]}]}


@pytest_asyncio.fixture
async def webhook(booking_client):
    client, sessions, postgres = booking_client
    config = Settings(_env_file=None, whatsapp_verify_token="test-verify", whatsapp_access_token="test-token",
                      whatsapp_phone_number_id="123456", whatsapp_api_version="v99.0", meta_app_secret="test-app-secret")
    sender = AsyncMock(spec=WhatsAppClient)
    calls = []
    fault = {"after_engine": False}
    calendar = AsyncMock(spec=CalendarService)
    calendar.sync_created_appointment.return_value = "google-event-123"
    fault["calendar"] = calendar

    class TestEngine(ConversationEngine):
        async def handle_message_in_transaction(self, business_id, phone, text):
            calls.append(text)
            result = await super().handle_message_in_transaction(business_id, phone, text)
            if fault["after_engine"]:
                raise RuntimeError("Simulated failure after engine")
            return result

    async with sessions.begin() as session:
        business = await session.get(Business, 1)
        business.phone_number = "+523300000001"

    def service(session=Depends(get_session)):
        fault["session"] = session
        return WebhookService(session, sender, config, TestEngine(session, clock=lambda: NOW),
                              calendar_service=calendar)

    app.dependency_overrides[get_webhook_service] = service
    app.dependency_overrides[get_whatsapp_settings] = lambda: config
    async def sign_request(request):
        if request.method == "POST" and request.url.path == URL:
            request.headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(
                b"test-app-secret", request.content, hashlib.sha256).hexdigest()
    client.event_hooks["request"].append(sign_request)
    try:
        yield client, sessions, sender, calls, fault, postgres
    finally:
        client.event_hooks["request"].remove(sign_request)
        app.dependency_overrides.pop(get_webhook_service, None)
        app.dependency_overrides.pop(get_whatsapp_settings, None)


@pytest.mark.parametrize("mode,token,status", [("subscribe","test-verify",200),
    ("subscribe","wrong",403),("other","test-verify",403)])
async def test_verification(webhook, mode, token, status):
    response = await webhook[0].get(URL, params={"hub.mode": mode, "hub.verify_token": token, "hub.challenge": "001234"})
    assert response.status_code == status
    if status == 200:
        assert response.text == "001234"
        assert response.headers["content-type"].startswith("text/plain")


def test_parser_all_entries_and_normalized_phone():
    payload = envelope()
    payload["entry"].extend(envelope("1", "wamid.second")["entry"])
    parsed = parse_messages(payload)
    assert [m.external_message_id for m in parsed] == ["wamid.test","wamid.second"]
    assert parsed[0].phone == "+523312345678"
    assert parsed[0].business_phone == "+523300000001"


async def test_duplicate_calls_engine_and_sender_once(webhook):
    client, sessions, sender, calls, _, _ = webhook
    for _ in range(2):
        assert (await client.post(URL, json=envelope())).status_code == 200
    assert calls == ["hola"]
    sender.send_text.assert_awaited_once()
    async with sessions() as session:
        inbound = await session.scalar(select(InboundMessage))
        assert inbound.processed_at is not None
        assert inbound.payload["sent_count"] == len(inbound.payload["responses"])
        assert await session.scalar(select(func.count()).select_from(InboundMessage)) == 1


async def confirm_setup(client):
    for i, text in enumerate(("hola","1","1","2","2")):
        assert (await client.post(URL, json=envelope(text, f"wamid.{i}"))).status_code == 200


async def test_confirmation_retry_never_duplicates_booking(webhook):
    client, sessions, sender, calls, _, _ = webhook
    await confirm_setup(client)
    payload = envelope("1", "wamid.confirm")
    assert (await client.post(URL, json=payload)).status_code == 200
    sent = sender.send_text.await_count
    assert (await client.post(URL, json=payload)).status_code == 200
    assert len(calls) == 6
    assert sender.send_text.await_count == sent
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 1
        conversation = await session.scalar(select(Conversation))
        assert conversation.state == "main_menu"
        assert conversation.context == {}
        assert await session.scalar(select(func.count()).select_from(InboundMessage)) == 6


@pytest.mark.parametrize("kind", ["status","image","other_number"])
async def test_ignored_events(webhook, kind):
    client, sessions, sender, calls, _, _ = webhook
    payload = envelope()
    value = payload["entry"][0]["changes"][0]["value"]
    if kind == "status":
        del value["messages"]
        value["statuses"] = [{"id":"wamid.outbound","status":"delivered"}]
    elif kind == "image":
        value["messages"][0]["type"] = "image"
    else:
        value["metadata"]["phone_number_id"] = "999999"
    assert (await client.post(URL, json=payload)).status_code == 200
    assert calls == []
    sender.send_text.assert_not_awaited()
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(InboundMessage)) == 0


async def test_invalid_payload_no_side_effect(webhook):
    client, _, sender, calls, _, _ = webhook
    payload = envelope()
    del payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
    assert (await client.post(URL, json=payload)).status_code == 400
    assert calls == []
    sender.send_text.assert_not_awaited()


async def test_delivery_failure_retries_without_reprocessing(webhook):
    client, sessions, sender, calls, _, _ = webhook
    sender.send_text.side_effect = [WhatsAppSendError("offline"), None]
    assert (await client.post(URL, json=envelope())).status_code == 503
    assert (await client.post(URL, json=envelope())).status_code == 200
    assert calls == ["hola"]
    assert sender.send_text.await_count == 2
    async with sessions() as session:
        assert (await session.scalar(select(InboundMessage))).payload["sent_count"] == 1


async def test_partial_delivery_resumes_only_pending_response(webhook):
    client, _, sender, _, _, _ = webhook

    # Reach SELECT_SERVICE, where an invalid option produces two responses.
    await client.post(URL, json=envelope("hola", "wamid.hello"))
    await client.post(URL, json=envelope("1", "wamid.menu"))

    sender.send_text.reset_mock()
    sender.send_text.side_effect = [None, WhatsAppSendError("offline"), None]

    payload = envelope("999", "wamid.invalid-service")
    assert (await client.post(URL, json=payload)).status_code == 503
    assert (await client.post(URL, json=payload)).status_code == 200

    texts = [call.args[1] for call in sender.send_text.await_args_list]
    assert sender.send_text.await_count == 3
    assert texts[0] != texts[1]
    assert texts[1] == texts[2]


async def test_batch_retry_preserves_processed_messages(webhook):
    client, _, sender, calls, _, _ = webhook
    payload = envelope()
    payload["entry"].extend(envelope("1", "wamid.second")["entry"])
    assert (await client.post(URL, json=payload)).status_code == 200
    assert (await client.post(URL, json=payload)).status_code == 200
    assert calls == ["hola", "1"]
    assert sender.send_text.await_count == 2


async def test_unmapped_business_is_not_hardcoded(webhook):
    client, _, sender, calls, _, _ = webhook
    payload = envelope()
    payload["entry"][0]["changes"][0]["value"]["metadata"]["display_phone_number"] = "523300000099"
    assert (await client.post(URL, json=payload)).status_code == 503
    assert calls == []
    sender.send_text.assert_not_awaited()


async def test_engine_failure_rolls_back_inbound_and_booking(webhook):
    client, sessions, sender, calls, fault, _ = webhook
    await confirm_setup(client)
    fault["after_engine"] = True
    async with sessions.begin() as session:
        (await session.get(Business, 1)).calendar_id = "primary"
    with pytest.raises(RuntimeError, match="Simulated failure"):
        await client.post(URL, json=envelope("1", "wamid.confirm"))
    fault["calendar"].sync_created_appointment.assert_not_awaited()
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 0
        assert await session.scalar(select(InboundMessage).where(InboundMessage.external_message_id == "wamid.confirm")) is None
        assert (await session.scalar(select(Conversation))).state == "confirm_appointment"
    fault["after_engine"] = False
    assert (await client.post(URL, json=envelope("1", "wamid.confirm"))).status_code == 200
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 1


async def test_concurrent_confirmation_retry_postgresql(webhook):
    client, sessions, sender, calls, _, postgres = webhook
    if not postgres:
        pytest.skip("Requires real PostgreSQL")
    await confirm_setup(client)
    responses = await asyncio.wait_for(asyncio.gather(
        client.post(URL, json=envelope("1", "wamid.confirm")),
        client.post(URL, json=envelope("1", "wamid.confirm"))), timeout=30)
    assert [r.status_code for r in responses] == [200,200]
    assert len(calls) == 6
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(Appointment)) == 1
        assert await session.scalar(select(func.count()).select_from(InboundMessage)) == 6


@pytest.mark.parametrize(
    ("phone", "expected_recipient"),
    [
        ("+523312345678", "523312345678"),
        ("+5215512345678", "525512345678"),
        ("+15555550199", "15555550199"),
    ],
)
async def test_graph_client_contract(phone, expected_recipient):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"messages": [{"id": "wamid.reply"}]},
        )

    config = Settings(
        _env_file=None,
        whatsapp_access_token="test-token",
        whatsapp_phone_number_id="123456",
        whatsapp_api_version="v99.0",
    )

    await WhatsAppClient(
        config,
        httpx.MockTransport(respond),
    ).send_text(phone, "Hola")

    assert str(requests[0].url) == (
        "https://graph.facebook.com/v99.0/123456/messages"
    )
    assert requests[0].headers["authorization"] == "Bearer test-token"

    import json

    assert json.loads(requests[0].content) == {
        "messaging_product": "whatsapp",
        "to": expected_recipient,
        "type": "text",
        "text": {"body": "Hola"},
    }


async def test_graph_client_sanitizes_provider_error():
    config = Settings(_env_file=None, whatsapp_access_token="test-token",
                      whatsapp_phone_number_id="123456", whatsapp_api_version="v99.0")
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error":"sensitive-provider-content"}))
    with pytest.raises(WhatsAppSendError) as error:
        await WhatsAppClient(config, transport).send_text("+523312345678", "Hola")
    assert "test-token" not in str(error.value)
    assert "sensitive" not in str(error.value)


async def enable_calendar(sessions):
    async with sessions.begin() as session:
        (await session.get(Business, 1)).calendar_id = "primary"


async def test_calendar_runs_after_commit_and_persists_id(webhook):
    client, sessions, sender, _, fault, _ = webhook
    await enable_calendar(sessions)
    await confirm_setup(client)
    sender.send_text.reset_mock()

    async def sync(**kwargs):
        assert not fault["session"].in_transaction()
        sender.send_text.assert_not_awaited()
        async with sessions() as session:
            appointment = await session.get(Appointment, kwargs["appointment"].id)
            assert appointment.status == "CONFIRMED"
            inbound = await session.scalar(select(InboundMessage).where(
                InboundMessage.external_message_id == "wamid.confirm"))
            assert inbound.processed_at is not None
            assert inbound.payload["sent_count"] == 0
        return "google-event-123"

    fault["calendar"].sync_created_appointment.side_effect = sync
    assert (await client.post(URL, json=envelope("1", "wamid.confirm"))).status_code == 200
    fault["calendar"].sync_created_appointment.assert_awaited_once()
    async with sessions() as session:
        assert (await session.scalar(select(Appointment))).calendar_event_id == "google-event-123"
    assert sender.send_text.await_count == 1


async def test_calendar_not_repeated_on_duplicate_or_delivery_retry(webhook):
    client, sessions, sender, _, fault, _ = webhook
    await enable_calendar(sessions)
    await confirm_setup(client)
    sender.send_text.reset_mock()
    sender.send_text.side_effect = [WhatsAppSendError("offline"), None]
    payload = envelope("1", "wamid.confirm")
    assert (await client.post(URL, json=payload)).status_code == 503
    assert (await client.post(URL, json=payload)).status_code == 200
    assert (await client.post(URL, json=payload)).status_code == 200
    fault["calendar"].sync_created_appointment.assert_awaited_once()
    assert sender.send_text.await_count == 2


async def test_calendar_failure_preserves_booking_processing_and_delivery(webhook):
    client, sessions, sender, _, fault, _ = webhook
    await enable_calendar(sessions)
    await confirm_setup(client)
    sender.send_text.reset_mock()
    fault["calendar"].sync_created_appointment.side_effect = GoogleCalendarError("insert", status_code=503)
    payload = envelope("1", "wamid.confirm")
    assert (await client.post(URL, json=payload)).status_code == 200
    assert (await client.post(URL, json=payload)).status_code == 200
    fault["calendar"].sync_created_appointment.assert_awaited_once()
    assert sender.send_text.await_count == 1
    async with sessions() as session:
        appointment = await session.scalar(select(Appointment))
        assert appointment.status == "CONFIRMED"
        assert appointment.calendar_event_id is None
        inbound = await session.scalar(select(InboundMessage).where(
            InboundMessage.external_message_id == "wamid.confirm"))
        assert inbound.processed_at is not None
        assert inbound.payload["sent_count"] == len(inbound.payload["responses"])
        assert (await session.scalar(select(Conversation))).state == "main_menu"


async def test_disabled_calendar_does_not_sync(webhook):
    client, _, _, _, fault, _ = webhook
    await confirm_setup(client)
    assert (await client.post(URL, json=envelope("1", "wamid.confirm"))).status_code == 200
    fault["calendar"].sync_created_appointment.assert_not_awaited()


async def test_linked_appointment_is_not_created_again(webhook):
    client, sessions, _, _, fault, _ = webhook
    await enable_calendar(sessions)
    await confirm_setup(client)
    assert (await client.post(URL, json=envelope("1", "wamid.confirm"))).status_code == 200
    fault["calendar"].sync_created_appointment.reset_mock()
    async with sessions() as session:
        async with session.begin():
            appointment_id = await session.scalar(select(Appointment.id))
        orchestrator = WebhookService(session, None, None, calendar_service=fault["calendar"])
        await orchestrator._sync_calendar(appointment_id)
    fault["calendar"].sync_created_appointment.assert_not_awaited()
