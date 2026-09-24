from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.integrations.google_calendar.errors import GoogleCalendarError
from app.models import Appointment, Business, Customer, Service
from app.services.calendar import CalendarEventData, CalendarService


@pytest.fixture
def booking_data():
    return {
        "appointment": Appointment(
            id=123, status="CONFIRMED", calendar_event_id=None,
            starts_at=datetime(2026, 9, 17, 18, tzinfo=timezone.utc),
            ends_at=datetime(2026, 9, 17, 19, tzinfo=timezone.utc),
        ),
        "business": Business(name="Bella Studio", timezone="America/Mexico_City", calendar_id="primary"),
        "service": Service(name="Corte"),
        "customer": Customer(name="", phone="+525512345678"),
    }


async def test_sync_created_appointment_uses_explicit_calendar_id(booking_data):
    booking_data["business"].calendar_id = None
    client = FakeGoogleCalendarClient()
    result = await CalendarService(client).sync_created_appointment(
        **booking_data,
        calendar_id="resolved-calendar",
    )
    assert result == "google-event-123"
    assert client.created[0]["calendar_id"] == "resolved-calendar"
    assert client.updated == client.deleted == []
    assert booking_data["appointment"].calendar_event_id is None


async def test_sync_created_appointment_returns_event_id(booking_data):
    client = FakeGoogleCalendarClient()
    result = await CalendarService(client).sync_created_appointment(
        **booking_data,
        calendar_id="primary",
    )
    assert result == "google-event-123"
    assert client.created == [{
        "calendar_id": "primary",
        "event": {
            "summary": "Corte - Bella Studio",
            "description": "Cliente: Sin nombre\nReserva creada por WhatsApp Booking",
            "start": {"dateTime": "2026-09-17T12:00:00-06:00", "timeZone": "America/Mexico_City"},
            "end": {"dateTime": "2026-09-17T13:00:00-06:00", "timeZone": "America/Mexico_City"},
        },
    }]
    assert client.updated == client.deleted == []
    assert booking_data["appointment"].calendar_event_id is None


async def test_sync_created_appointment_failure_preserves_appointment(booking_data):
    error = GoogleCalendarError("insert", status_code=503)

    class FailingClient(FakeGoogleCalendarClient):
        async def create_event(self, **kwargs):
            self.created.append(kwargs)
            raise error

    appointment = booking_data["appointment"]
    before = {column.key: getattr(appointment, column.key)
              for column in Appointment.__table__.columns}
    client = FailingClient()
    with pytest.raises(GoogleCalendarError) as caught:
        await CalendarService(client).sync_created_appointment(
            **booking_data,
            calendar_id="primary",
        )
    assert caught.value is error
    assert len(client.created) == 1
    assert client.updated == client.deleted == []
    assert {column.key: getattr(appointment, column.key)
            for column in Appointment.__table__.columns} == before
    assert appointment.status == "CONFIRMED"
    assert appointment.calendar_event_id is None


def test_phone_used_as_placeholder_name_is_not_exported(booking_data):
    booking_data["customer"].name = booking_data["customer"].phone
    event = CalendarEventData.from_appointment(**booking_data)
    assert event.description == "Cliente: Sin nombre\nReserva creada por WhatsApp Booking"
    assert booking_data["customer"].phone not in str(event.to_payload())


class FakeGoogleCalendarClient:
    def __init__(self):
        self.created = []
        self.updated = []
        self.deleted = []

    async def create_event(self, **kwargs):
        self.created.append(kwargs)
        return "google-event-123"

    async def update_event(self, **kwargs):
        self.updated.append(kwargs)

    async def delete_event(self, **kwargs):
        self.deleted.append(kwargs)


async def test_reschedule_skips_missing_event(booking_data):
    booking_data["appointment"].calendar_event_id = None
    client = FakeGoogleCalendarClient()
    await CalendarService(client).sync_rescheduled_appointment(
        **booking_data,
        calendar_id="primary",
    )
    assert client.created == client.updated == client.deleted == []


async def test_reschedule_uses_explicit_calendar_without_legacy_id(booking_data):
    booking_data["business"].calendar_id = None
    booking_data["appointment"].calendar_event_id = "existing-event"
    client = FakeGoogleCalendarClient()

    await CalendarService(client).sync_rescheduled_appointment(
        **booking_data,
        calendar_id="resolved-calendar",
    )

    assert client.updated[0]["calendar_id"] == "resolved-calendar"
    assert client.updated[0]["event_id"] == "existing-event"


async def test_reschedule_updates_same_event_once_without_create(booking_data):
    appointment = booking_data["appointment"]
    appointment.calendar_event_id = "existing-event"
    client = FakeGoogleCalendarClient()
    await CalendarService(client).sync_rescheduled_appointment(
        **booking_data,
        calendar_id="primary",
    )
    assert client.updated == [{"calendar_id": "primary", "event_id": "existing-event",
                               "event": CalendarEventData.from_appointment(**booking_data).to_payload()}]
    assert client.created == client.deleted == []
    assert appointment.calendar_event_id == "existing-event"


async def test_reschedule_failure_keeps_dates_and_event_id(booking_data):
    appointment = booking_data["appointment"]
    appointment.calendar_event_id = "existing-event"
    before = (appointment.starts_at, appointment.ends_at, appointment.calendar_event_id)
    error = GoogleCalendarError("update", status_code=503)

    class FailingUpdate(FakeGoogleCalendarClient):
        async def update_event(self, **kwargs):
            raise error

    client = FailingUpdate()
    with pytest.raises(GoogleCalendarError) as caught:
        await CalendarService(client).sync_rescheduled_appointment(
            **booking_data,
            calendar_id="primary",
        )
    assert caught.value is error
    assert (appointment.starts_at, appointment.ends_at, appointment.calendar_event_id) == before
    assert client.created == []


async def test_cancel_skips_missing_event(booking_data):
    appointment = booking_data["appointment"]
    business = booking_data["business"]
    appointment.calendar_event_id = None
    client = FakeGoogleCalendarClient()
    await CalendarService(client).sync_cancelled_appointment(
        appointment=appointment,
        business=business,
        calendar_id="primary",
    )
    assert client.created == client.updated == client.deleted == []


async def test_cancel_uses_explicit_calendar_without_legacy_id(booking_data):
    appointment = booking_data["appointment"]
    business = booking_data["business"]
    business.calendar_id = None
    appointment.calendar_event_id = "existing-event"
    client = FakeGoogleCalendarClient()

    await CalendarService(client).sync_cancelled_appointment(
        appointment=appointment,
        business=business,
        calendar_id="resolved-calendar",
    )

    assert client.deleted == [
        {
            "calendar_id": "resolved-calendar",
            "event_id": "existing-event",
        }
    ]


async def test_cancel_deletes_existing_event_and_preserves_id(booking_data):
    appointment = booking_data["appointment"]
    appointment.status = "CANCELLED"
    appointment.calendar_event_id = "existing-event"
    client = FakeGoogleCalendarClient()
    await CalendarService(client).sync_cancelled_appointment(
        appointment=appointment,
        business=booking_data["business"],
        calendar_id="primary",
    )
    assert client.deleted == [{"calendar_id": "primary", "event_id": "existing-event"}]
    assert client.created == client.updated == []
    assert appointment.calendar_event_id == "existing-event"


async def test_cancel_failure_propagates_without_mutating_appointment(booking_data):
    appointment = booking_data["appointment"]
    appointment.status = "CANCELLED"
    appointment.calendar_event_id = "existing-event"
    error = GoogleCalendarError("delete", status_code=503)

    class FailingDelete(FakeGoogleCalendarClient):
        async def delete_event(self, **kwargs):
            raise error

    with pytest.raises(GoogleCalendarError) as caught:
        await CalendarService(FailingDelete()).sync_cancelled_appointment(
            appointment=appointment,
            business=booking_data["business"],
            calendar_id="primary",
        )
    assert caught.value is error
    assert appointment.status == "CANCELLED"
    assert appointment.calendar_event_id == "existing-event"


@pytest.fixture
def event():
    return CalendarEventData.from_appointment(
        appointment=Appointment(
            starts_at=datetime(2026, 9, 17, 18, tzinfo=timezone.utc),
            ends_at=datetime(2026, 9, 17, 19, tzinfo=timezone.utc),
        ),
        business=Business(name="Bella Studio", timezone="America/Mexico_City"),
        service=Service(name="Corte"),
        customer=Customer(name="Marco", phone="+525512345678"),
    )


async def test_create_returns_external_event_id(event):
    client = FakeGoogleCalendarClient()
    event_id = await CalendarService(client).create(calendar_id="primary", event=event)
    assert event_id == "google-event-123"
    assert client.created == [{
        "calendar_id": "primary",
        "event": {
            "summary": "Corte - Bella Studio",
            "description": "Cliente: Marco\nReserva creada por WhatsApp Booking",
            "start": {"dateTime": "2026-09-17T12:00:00-06:00", "timeZone": "America/Mexico_City"},
            "end": {"dateTime": "2026-09-17T13:00:00-06:00", "timeZone": "America/Mexico_City"},
        },
    }]
    assert "+525512345678" not in str(client.created)
    assert client.updated == client.deleted == []


async def test_update_uses_existing_event_id(event):
    client = FakeGoogleCalendarClient()
    appointment = Appointment(calendar_event_id="google-event-123")
    result = await CalendarService(client).update(
        calendar_id="business-calendar", event_id=appointment.calendar_event_id, event=event,
    )
    assert result is None
    assert client.updated == [{
        "calendar_id": "business-calendar", "event_id": "google-event-123",
        "event": event.to_payload(),
    }]
    assert client.created == client.deleted == []


async def test_delete_uses_existing_event_id():
    client = FakeGoogleCalendarClient()
    appointment = Appointment(calendar_event_id="google-event-123")
    result = await CalendarService(client).delete(
        calendar_id="business-calendar", event_id=appointment.calendar_event_id,
    )
    assert result is None
    assert client.deleted == [{"calendar_id": "business-calendar", "event_id": "google-event-123"}]
    assert client.created == client.updated == []


@pytest.mark.parametrize("invalid", ["naive", "equal", "reversed"])
async def test_invalid_dates_do_not_call_client(event, invalid):
    if invalid == "naive":
        event = replace(event, start_at=event.start_at.replace(tzinfo=None))
    elif invalid == "equal":
        event = replace(event, end_at=event.start_at)
    else:
        event = replace(event, start_at=event.end_at, end_at=event.start_at)
    client = FakeGoogleCalendarClient()
    with pytest.raises(ValueError):
        await CalendarService(client).create(calendar_id="primary", event=event)
    assert client.created == []


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_google_errors_propagate(event, operation):
    error = GoogleCalendarError(operation, status_code=503)

    async def fail(**kwargs):
        raise error

    client = FakeGoogleCalendarClient()
    setattr(client, f"{operation}_event", fail)
    kwargs = {"calendar_id": "primary"}
    if operation != "create":
        kwargs["event_id"] = "google-event-123"
    if operation != "delete":
        kwargs["event"] = event
    with pytest.raises(GoogleCalendarError) as caught:
        await getattr(CalendarService(client), operation)(**kwargs)
    assert caught.value is error
