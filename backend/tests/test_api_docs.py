import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_api_documentation_is_available_when_enabled(path: str):
    app = create_app(Settings(_env_file=None, api_docs_enabled=True))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(path)

    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_api_documentation_is_unavailable_when_disabled(path: str):
    app = create_app(Settings(_env_file=None, api_docs_enabled=False))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(path)

    assert response.status_code == 404
