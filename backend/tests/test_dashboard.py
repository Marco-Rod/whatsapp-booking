from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from test_booking import booking_client
from app.models import Appointment, AppointmentReminder, Business, Customer


async def add(sessions, start="2026-09-18T16:00:00+00:00", *, business_id=1,
              status="CONFIRMED", linked=False, customer_id=None):
    start = datetime.fromisoformat(start)
    async with sessions.begin() as session:
        appointment = Appointment(business_id=business_id, service_id=business_id,
            starts_at=start, ends_at=start + timedelta(hours=1), status=status,
            customer_id=customer_id, calendar_event_id="private-external-id" if linked else None)
        session.add(appointment)
        await session.flush()
        return appointment.id


async def get(client, day="2026-09-18", business_id=1):
    return await client.get(f"/api/v1/businesses/{business_id}/dashboard", params={"date": day})


async def test_missing_business_is_404(booking_client):
    assert (await get(booking_client[0], business_id=999)).status_code == 404


@pytest.mark.parametrize("origin,allowed", [
    ("http://127.0.0.1:5173", True), ("https://untrusted.example", False),
])
async def test_dashboard_cors(booking_client, origin, allowed):
    response = await booking_client[0].options(
        "/api/v1/businesses/1/dashboard",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == (200 if allowed else 400)
    assert response.headers.get("access-control-allow-origin") == (origin if allowed else None)


async def test_empty_day(booking_client):
    response = await get(booking_client[0])
    assert response.status_code == 200
    assert response.json() == {"date": "2026-09-18", "timezone": "America/Mexico_City",
        "summary": {"total": 0, "confirmed": 0, "cancelled": 0}, "appointments": []}


async def test_order_summary_booleans_and_private_fields(booking_client):
    client, sessions, _ = booking_client
    async with sessions.begin() as session:
        customer = Customer(business_id=1, name="Cliente", phone="+15555550123")
        session.add(customer)
        await session.flush()
        customer_id = customer.id
    later = await add(sessions, "2026-09-18T18:00:00+00:00", status="CANCELLED", linked=True)
    earlier = await add(sessions, linked=True, customer_id=customer_id)
    pending = await add(sessions, "2026-09-18T17:00:00+00:00")
    await add(sessions, status="PENDING")
    await add(sessions, status="COMPLETED")
    async with sessions.begin() as session:
        # Multiple historical reminders must not multiply appointment rows.
        session.add_all([
            AppointmentReminder(appointment_id=earlier, scheduled_for=datetime.fromisoformat("2026-09-16T16:00:00+00:00"),
                                sent_at=datetime.fromisoformat("2026-09-16T16:05:00+00:00")),
            AppointmentReminder(appointment_id=earlier, scheduled_for=datetime.fromisoformat("2026-09-17T16:00:00+00:00")),
            AppointmentReminder(appointment_id=pending, scheduled_for=datetime.fromisoformat("2026-09-17T17:00:00+00:00")),
        ])
    response = await get(client)
    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == {"total": 3, "confirmed": 2, "cancelled": 1}
    assert [a["id"] for a in data["appointments"]] == [earlier, pending, later]
    first, second, third = data["appointments"]
    assert first == {"id": earlier, "starts_at": "2026-09-18T10:00:00-06:00",
        "ends_at": "2026-09-18T11:00:00-06:00", "status": "CONFIRMED",
        "service": {"id": 1, "name": "Cut"}, "customer": {"id": customer_id, "name": "Cliente"},
        "calendar_synced": True, "reminder_sent": True}
    assert second["calendar_synced"] is False and second["reminder_sent"] is False
    assert third["customer"] is None and third["calendar_synced"] is True and third["reminder_sent"] is False
    for forbidden in ("phone", "+15555550123", "calendar_event_id", "private-external-id", "sent_at", "claim_token"):
        assert forbidden not in response.text


async def test_utc_dates_use_local_half_open_day(booking_client):
    client, sessions, _ = booking_client
    previous = await add(sessions, "2026-09-18T01:00:00+00:00")
    midnight = await add(sessions, "2026-09-18T06:00:00+00:00")
    last = await add(sessions, "2026-09-19T05:59:59+00:00")
    following = await add(sessions, "2026-09-19T06:00:00+00:00")
    assert [a["id"] for a in (await get(client, "2026-09-17")).json()["appointments"]] == [previous]
    assert [a["id"] for a in (await get(client)).json()["appointments"]] == [midnight, last]
    assert [a["id"] for a in (await get(client, "2026-09-19")).json()["appointments"]] == [following]


async def test_other_business_never_appears(booking_client):
    client, sessions, _ = booking_client
    own = await add(sessions)
    other = await add(sessions, business_id=2)
    data = (await get(client)).json()
    assert data["summary"]["total"] == 1
    assert [a["id"] for a in data["appointments"]] == [own]
    assert [a["id"] for a in (await get(client, business_id=2)).json()["appointments"]] == [other]


async def test_phone_placeholder_name_is_not_exposed(booking_client):
    client, sessions, _ = booking_client
    async with sessions.begin() as session:
        customer = Customer(business_id=1, name="+15555550123", phone="+15555550123")
        session.add(customer)
        await session.flush()
        customer_id = customer.id
    await add(sessions, customer_id=customer_id)
    response = await get(client)
    assert response.json()["appointments"][0]["customer"] == {"id": customer_id, "name": "Sin nombre"}
    assert "+15555550123" not in response.text


@pytest.mark.parametrize("day,start,end", [
    ("2026-03-08", "2026-03-08T05:00:00+00:00", "2026-03-09T04:00:00+00:00"),
    ("2026-11-01", "2026-11-01T04:00:00+00:00", "2026-11-02T05:00:00+00:00"),
])
async def test_dst_day_uses_local_midnights(booking_client, day, start, end):
    client, sessions, _ = booking_client
    async with sessions.begin() as session:
        (await session.get(Business, 1)).timezone = "America/New_York"
    first = await add(sessions, start)
    last = await add(sessions, (datetime.fromisoformat(end) - timedelta(seconds=1)).isoformat())
    await add(sessions, end)
    await add(sessions, (datetime.fromisoformat(start) - timedelta(seconds=1)).isoformat())
    assert [a["id"] for a in (await get(client, day)).json()["appointments"]] == [first, last]


async def test_fifty_appointments_use_two_selects(booking_client):
    client, sessions, _ = booking_client
    async with sessions.begin() as session:
        for minute in range(50):
            start = datetime.fromisoformat("2026-09-18T16:00:00+00:00") + timedelta(minutes=minute)
            session.add(Appointment(business_id=1, service_id=1, starts_at=start,
                                   ends_at=start + timedelta(hours=1), status="CONFIRMED"))
    queries = []
    engine = sessions.kw["bind"].sync_engine

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = await get(client)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 50
    assert len(queries) == 2


@pytest.mark.parametrize("day", ["not-a-date", "2026-02-30", "9999-12-31"])
async def test_invalid_dates_are_422(booking_client, day):
    assert (await get(booking_client[0], day)).status_code == 422
