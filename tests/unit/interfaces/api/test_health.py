"""Health liveness does not require PostgreSQL."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.interfaces.api.main import app


@pytest.mark.asyncio
async def test_liveness_does_not_probe_database() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        live = await client.get("/api/v1/health/live")
        compat = await client.get("/api/v1/health")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"
    assert compat.status_code == 200
    assert "version" in live.json()
