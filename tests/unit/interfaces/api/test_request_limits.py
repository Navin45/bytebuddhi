"""HTTP request size limit."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.interfaces.api.main import app


@pytest.mark.asyncio
async def test_oversize_content_length_is_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/conversations",
            content=b"{}",
            headers={"Content-Length": str(5_000_000), "Content-Type": "application/json"},
        )
    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


@pytest.mark.asyncio
async def test_security_headers_present_on_liveness() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/health/live")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
