from datetime import time

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from test_booking import booking_client  # noqa: F401

from app.models import Business, BusinessHours, Service
from app.security.admin_tokens import hash_admin_token
from app.core.config import settings


BASE_URL = "/api/v1/onboarding"


async def authorize_business(
    sessions,
    *,
    business_id=1,
    token="business-admin-token",
):
    settings.admin_session_secret = SecretStr(
        "test-admin-session-secret"
    )
    settings.admin_session_max_age_seconds = 7 * 24 * 60 * 60
    settings.admin_session_cookie_secure = False
    settings.admin_session_cookie_samesite = "lax"
    async with sessions.begin() as session:
        business = await session.get(Business, business_id)
        business.admin_token_hash = hash_admin_token(token)
    return token


async def login_business(client, sessions, **kwargs):
    token = await authorize_business(sessions, **kwargs)
    response = await client.post(
        "/api/v1/admin/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    return {}


def hours_payload():
    return {
        "hours": [
            {
                "weekday": weekday,
                "start_time": "09:00",
                "end_time": "18:00",
                "is_closed": False,
            }
            for weekday in range(6)
        ]
        + [{"weekday": 6, "is_closed": True}]
    }


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": "Basic credentials"},
    ],
    ids=["missing", "incorrect", "wrong-scheme"],
)
async def test_onboarding_requires_valid_session_cookie(
    booking_client,
    headers,
):
    client, sessions, _ = booking_client
    await authorize_business(sessions)

    response = await client.get(
        f"{BASE_URL}/status",
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid business admin credentials"
    }


async def test_get_business_configuration_returns_only_editable_fields(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(client, sessions)

    response = await client.get(f"{BASE_URL}/business", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "name": "One",
        "timezone": "America/Mexico_City",
    }


async def test_get_business_configuration_requires_session(
    booking_client,
):
    client, sessions, _ = booking_client
    await authorize_business(sessions)

    response = await client.get(f"{BASE_URL}/business")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid business admin credentials"
    }


async def test_get_business_configuration_uses_session_business_only(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(
        client,
        sessions,
        business_id=2,
        token="second-business-token",
    )

    response = await client.get(
        f"{BASE_URL}/business?business_id=1",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "Two",
        "timezone": "America/Mexico_City",
    }


async def test_get_services_configuration_returns_active_editable_fields_only(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(client, sessions)

    response = await client.get(f"{BASE_URL}/services", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "services": [
            {"name": "Cut", "duration_minutes": 60},
            {"name": "Long", "duration_minutes": 120},
        ]
    }


async def test_get_services_configuration_excludes_inactive_services(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(client, sessions)

    response = await client.get(f"{BASE_URL}/services", headers=headers)

    assert "Inactive" not in {
        service["name"] for service in response.json()["services"]
    }


async def test_get_services_configuration_requires_session(booking_client):
    client, sessions, _ = booking_client
    await authorize_business(sessions)

    response = await client.get(f"{BASE_URL}/services")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid business admin credentials"
    }


async def test_get_services_configuration_uses_session_business_only(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(
        client,
        sessions,
        business_id=2,
        token="second-business-token",
    )

    response = await client.get(
        f"{BASE_URL}/services?business_id=1",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "services": [{"name": "Cut", "duration_minutes": 60}]
    }


async def test_get_hours_configuration_returns_all_days_in_order(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(client, sessions)

    response = await client.get(f"{BASE_URL}/hours", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "hours": [
            {
                "day_of_week": weekday,
                "is_open": weekday == 5,
                "open_time": "09:00" if weekday == 5 else None,
                "close_time": "18:00" if weekday == 5 else None,
            }
            for weekday in range(7)
        ]
    }


async def test_get_hours_configuration_keeps_closed_days_without_times(
    booking_client,
):
    client, sessions, _ = booking_client
    async with sessions.begin() as session:
        sunday = await session.get(BusinessHours, 2)
        sunday.is_closed = True
        sunday.start_time = time(10)
        sunday.end_time = time(16)
    headers = await login_business(client, sessions)

    response = await client.get(f"{BASE_URL}/hours", headers=headers)

    assert response.status_code == 200
    assert response.json()["hours"][6] == {
        "day_of_week": 6,
        "is_open": False,
        "open_time": None,
        "close_time": None,
    }


async def test_get_hours_configuration_requires_session(booking_client):
    client, sessions, _ = booking_client
    await authorize_business(sessions)

    response = await client.get(f"{BASE_URL}/hours")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid business admin credentials"
    }


async def test_get_hours_configuration_uses_session_business_only(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(
        client,
        sessions,
        business_id=2,
        token="second-business-token",
    )
    async with sessions.begin() as session:
        saturday = await session.get(BusinessHours, 1)
        saturday.start_time = time(8)
        saturday.end_time = time(14)

    response = await client.get(
        f"{BASE_URL}/hours?business_id=1",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["hours"][5] == {
        "day_of_week": 5,
        "is_open": True,
        "open_time": "09:00",
        "close_time": "18:00",
    }


async def test_onboarding_token_can_modify_only_its_business(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(
        client,
        sessions,
        business_id=2,
        token="second-business-token",
    )

    response = await client.put(
        f"{BASE_URL}/business",
        headers=headers,
        json={
            "name": "Second Studio",
            "timezone": "America/Mexico_City",
        },
    )

    assert response.status_code == 200
    async with sessions() as session:
        first = await session.get(Business, 1)
        second = await session.get(Business, 2)
        assert first.name == "One"
        assert second.name == "Second Studio"


@pytest.mark.parametrize(
    "extra",
    [
        {"business_id": 2},
        {"phone_number": "+15555550199"},
        {"admin_token_hash": "injected"},
        {"onboarding_completed_at": "2026-09-25T12:00:00Z"},
    ],
)
async def test_business_payload_rejects_protected_fields(
    booking_client,
    extra,
):
    client, sessions, _ = booking_client
    headers = await login_business(client, sessions)

    response = await client.put(
        f"{BASE_URL}/business",
        headers=headers,
        json={
            "name": "Changed",
            "timezone": "America/Mexico_City",
            **extra,
        },
    )

    assert response.status_code == 422
    async with sessions() as session:
        assert (await session.get(Business, 1)).name == "One"


async def test_nested_service_payload_rejects_business_id(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(client, sessions)

    response = await client.put(
        f"{BASE_URL}/services",
        headers=headers,
        json={
            "services": [
                {
                    "name": "Cut",
                    "duration_minutes": 60,
                    "business_id": 2,
                }
            ]
        },
    )

    assert response.status_code == 422


async def test_invalid_put_keeps_previous_state(booking_client):
    client, sessions, _ = booking_client
    headers = await login_business(client, sessions)

    response = await client.put(
        f"{BASE_URL}/business",
        headers=headers,
        json={"name": "Changed", "timezone": "Invalid/Zone"},
    )

    assert response.status_code == 422
    async with sessions() as session:
        business = await session.get(Business, 1)
        assert business.name == "One"
        assert business.timezone == "America/Mexico_City"


async def test_onboarding_configuration_endpoints_return_progress(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(client, sessions)

    business = await client.put(
        f"{BASE_URL}/business",
        headers=headers,
        json={
            "name": "Bella Studio",
            "timezone": "America/Mexico_City",
        },
    )
    services = await client.put(
        f"{BASE_URL}/services",
        headers=headers,
        json={
            "services": [
                {"name": "Corte", "duration_minutes": 60},
                {"name": "Tinte", "duration_minutes": 90},
            ]
        },
    )
    hours = await client.put(
        f"{BASE_URL}/hours",
        headers=headers,
        json=hours_payload(),
    )
    status = await client.get(
        f"{BASE_URL}/status",
        headers=headers,
    )

    assert business.status_code == 200
    assert services.status_code == 200
    assert hours.status_code == 200
    assert status.status_code == 200
    assert status.json() == {
        "completed": False,
        "ready": True,
        "steps": {
            "business": True,
            "services": True,
            "hours": True,
            "calendar": False,
        },
    }
    async with sessions() as session:
        active = list(
            await session.scalars(
                select(Service).where(
                    Service.business_id == 1,
                    Service.is_active.is_(True),
                )
            )
        )
        configured_hours = list(
            await session.scalars(
                select(BusinessHours).where(
                    BusinessHours.business_id == 1
                )
            )
        )
        assert {row.name for row in active} == {"Corte", "Tinte"}
        assert len(configured_hours) == 7


async def test_complete_incomplete_returns_missing_steps(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(client, sessions)

    response = await client.post(
        f"{BASE_URL}/complete",
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Onboarding is incomplete",
        "missing_steps": ["hours"],
    }
    async with sessions() as session:
        business = await session.get(Business, 1)
        assert business.onboarding_completed_at is None


async def test_complete_requires_session(booking_client):
    client, sessions, _ = booking_client
    await authorize_business(sessions)

    response = await client.post(f"{BASE_URL}/complete")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Invalid business admin credentials"
    }


async def test_complete_uses_session_business_only(booking_client):
    client, sessions, _ = booking_client
    headers = await login_business(client, sessions)
    assert (
        await client.put(
            f"{BASE_URL}/hours",
            headers=headers,
            json=hours_payload(),
        )
    ).status_code == 200

    response = await client.post(
        f"{BASE_URL}/complete?business_id=2",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["completed"] is True
    async with sessions() as session:
        assert (await session.get(Business, 1)).onboarding_completed_at is not None
        assert (await session.get(Business, 2)).onboarding_completed_at is None


async def test_complete_is_idempotent_without_calendar(
    booking_client,
):
    client, sessions, _ = booking_client
    headers = await login_business(client, sessions)
    assert (
        await client.put(
            f"{BASE_URL}/hours",
            headers=headers,
            json=hours_payload(),
        )
    ).status_code == 200

    first = await client.post(
        f"{BASE_URL}/complete",
        headers=headers,
    )
    async with sessions() as session:
        original = (
            await session.get(Business, 1)
        ).onboarding_completed_at
    second = await client.post(
        f"{BASE_URL}/complete",
        headers=headers,
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["completed"] is True
    assert first.json()["ready"] is True
    assert first.json()["steps"]["calendar"] is False
    async with sessions() as session:
        current = (
            await session.get(Business, 1)
        ).onboarding_completed_at
        assert current == original


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE"])
async def test_onboarding_cors_preflight_allows_credentials(
    booking_client,
    method,
):
    client, _, _ = booking_client

    response = await client.options(
        f"{BASE_URL}/business",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": (
                "authorization,content-type"
            ),
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://localhost:5173"
    )
    assert method in response.headers["access-control-allow-methods"]
    assert "authorization" in response.headers[
        "access-control-allow-headers"
    ].lower()
    assert "content-type" in response.headers[
        "access-control-allow-headers"
    ].lower()
    assert response.headers[
        "access-control-allow-credentials"
    ] == "true"


async def test_cors_rejects_unconfigured_origin(booking_client):
    client, _, _ = booking_client

    response = await client.options(
        f"{BASE_URL}/business",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": (
                "authorization,content-type"
            ),
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
