import pytest

from test_booking import booking_client  # noqa: F401


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("POST", "/api/v1/appointments", {}),
        ("GET", "/api/v1/appointments/1", None),
        ("POST", "/api/v1/appointments/1/cancel", None),
        (
            "POST",
            "/api/v1/appointments/1/reschedule",
            {"starts_at": "2026-09-19T12:00:00-06:00"},
        ),
        (
            "GET",
            "/api/v1/availability?business_id=1&service_id=1&date=2026-09-19",
            None,
        ),
    ],
)
async def test_obsolete_public_booking_http_routes_are_not_exposed(
    booking_client,
    method,
    path,
    json,
):
    response = await booking_client[0].request(method, path, json=json)

    assert response.status_code == 404
