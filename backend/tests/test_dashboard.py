from datetime import datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import event

from test_booking import booking_client
from app.models import Appointment, AppointmentReminder, Business, Customer
from app.core.config import settings
from app.security.admin_tokens import hash_admin_token


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


async def login_business(client, sessions, *, business_id=1):
    settings.admin_session_secret = SecretStr("test-admin-session-secret")
    settings.admin_session_cookie_secure = False
    settings.admin_session_cookie_samesite = "lax"
    token = f"dashboard-admin-token-{business_id}"
    async with sessions.begin() as session:
        business = await session.get(Business, business_id)
        business.admin_token_hash = hash_admin_token(token)

    response = await client.post(
        "/api/v1/admin/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    return {}


async def get_admin(client, day="2026-09-18", **params):
    return await client.get(
        "/api/v1/admin/dashboard",
        params={"date": day, **params},
    )


async def get(client, sessions, day="2026-09-18", business_id=1):
    await login_business(client, sessions, business_id=business_id)
    return await get_admin(client, day)


async def test_legacy_dashboard_endpoint_is_404(booking_client):
    response = await booking_client[0].get(
        "/api/v1/businesses/1/dashboard", params={"date": "2026-09-18"}
    )

    assert response.status_code == 404


async def test_admin_dashboard_requires_session(booking_client):
    response = await get_admin(booking_client[0])

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid business admin credentials"
    }


async def test_admin_dashboard_uses_session_business_and_preserves_dto(
    booking_client,
):
    client, sessions, _ = booking_client
    own = await add(sessions, business_id=1)
    other = await add(sessions, business_id=2)
    await login_business(client, sessions, business_id=2)

    response = await get_admin(client, business_id=1)

    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 1
    assert response.json()["appointments"][0]["id"] == other
    assert response.json()["appointments"][0]["id"] != own


@pytest.mark.parametrize("origin,allowed", [
    ("http://127.0.0.1:5173", True), ("https://untrusted.example", False),
])
async def test_dashboard_cors(booking_client, origin, allowed):
    response = await booking_client[0].options(
        "/api/v1/admin/dashboard",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == (200 if allowed else 400)
    assert response.headers.get("access-control-allow-origin") == (origin if allowed else None)


async def test_empty_day(booking_client):
    response = await get(*booking_client[:2])
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
    response = await get(client, sessions)
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
    assert [a["id"] for a in (await get(client, sessions, "2026-09-17")).json()["appointments"]] == [previous]
    assert [a["id"] for a in (await get(client, sessions)).json()["appointments"]] == [midnight, last]
    assert [a["id"] for a in (await get(client, sessions, "2026-09-19")).json()["appointments"]] == [following]


async def test_other_business_never_appears(booking_client):
    client, sessions, _ = booking_client
    own = await add(sessions)
    other = await add(sessions, business_id=2)
    data = (await get(client, sessions)).json()
    assert data["summary"]["total"] == 1
    assert [a["id"] for a in data["appointments"]] == [own]
    assert [a["id"] for a in (await get(client, sessions, business_id=2)).json()["appointments"]] == [other]


async def test_phone_placeholder_name_is_not_exposed(booking_client):
    client, sessions, _ = booking_client
    async with sessions.begin() as session:
        customer = Customer(business_id=1, name="+15555550123", phone="+15555550123")
        session.add(customer)
        await session.flush()
        customer_id = customer.id
    await add(sessions, customer_id=customer_id)
    response = await get(client, sessions)
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
    assert [a["id"] for a in (await get(client, sessions, day)).json()["appointments"]] == [first, last]


async def test_fifty_appointments_use_two_dashboard_selects_after_session_validation(booking_client):
    client, sessions, _ = booking_client
    async with sessions.begin() as session:
        for minute in range(50):
            start = datetime.fromisoformat("2026-09-18T16:00:00+00:00") + timedelta(minutes=minute)
            session.add(Appointment(business_id=1, service_id=1, starts_at=start,
                                   ends_at=start + timedelta(hours=1), status="CONFIRMED"))
    queries = []
    engine = sessions.kw["bind"].sync_engine
    await login_business(client, sessions)

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = await get_admin(client)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 50
    # The first lookup validates admin_session; dashboard retrieval remains two SELECTs.
    assert len(queries) == 3


@pytest.mark.parametrize("day", ["not-a-date", "2026-02-30", "9999-12-31"])
async def test_invalid_dates_are_422(booking_client, day):
    assert (await get(booking_client[0], booking_client[1], day)).status_code == 422
