"""Unit tests for ExternalHttpClient: retries, timeouts, error mapping, and security bounding."""

import httpx
import pytest

from app.domain.exceptions.connector_exceptions import (
    ConnectorAuthenticationError,
    ConnectorAuthorizationError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    ConnectorServiceError,
    ConnectorTimeoutError,
)
from app.infrastructure.http.external_client import ExternalHttpClient


@pytest.mark.asyncio
async def test_external_client_status_error_mapping():
    """Verify HTTP status codes map to specific Connector exceptions."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/401" in url:
            return httpx.Response(401, json={"message": "Bad credentials"})
        if "/403" in url:
            return httpx.Response(403, json={"message": "Permission denied"})
        if "/404" in url:
            return httpx.Response(404, json={"message": "Resource not found"})
        if "/429" in url:
            return httpx.Response(429, headers={"Retry-After": "15"}, json={"message": "Rate limited"})
        if "/500" in url:
            return httpx.Response(500, json={"message": "Internal error"})
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as raw_client:
        client = ExternalHttpClient(client=raw_client, default_timeout=5.0, max_retries=1)

        # 401
        with pytest.raises(ConnectorAuthenticationError):
            await client.get("https://api.example.com/401")

        # 403
        with pytest.raises(ConnectorAuthorizationError):
            await client.get("https://api.example.com/403")

        # 404
        with pytest.raises(ConnectorNotFoundError):
            await client.get("https://api.example.com/404")

        # 429
        with pytest.raises(ConnectorRateLimitError) as exc_info:
            await client.get("https://api.example.com/429")
        assert exc_info.value.retry_after == 15

        # 500
        with pytest.raises(ConnectorServiceError):
            await client.post("https://api.example.com/500", json_data={"a": 1})


@pytest.mark.asyncio
async def test_external_client_retry_safety():
    """Verify idempotent GET retries on 503, while mutating POST does NOT retry."""
    get_call_count = 0
    post_call_count = 0

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_call_count, post_call_count
        if request.method == "GET":
            get_call_count += 1
            if get_call_count < 3:
                return httpx.Response(503, json={"error": "Unavailable"})
            return httpx.Response(200, json={"data": "recovered"})
        if request.method == "POST":
            post_call_count += 1
            return httpx.Response(503, json={"error": "Unavailable"})
        return httpx.Response(200)

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as raw_client:
        client = ExternalHttpClient(client=raw_client, max_retries=3, default_timeout=5.0)

        # GET should succeed on the 3rd attempt
        resp = await client.get("https://api.example.com/data")
        assert resp.status_code == 200
        assert resp.json() == {"data": "recovered"}
        assert get_call_count == 3

        # POST should fail immediately without retrying
        with pytest.raises(ConnectorServiceError):
            await client.post("https://api.example.com/mutate", json_data={"foo": "bar"})
        assert post_call_count == 1  # No retries for mutating operations!


@pytest.mark.asyncio
async def test_external_client_timeout_handling():
    """Verify httpx.TimeoutException is mapped to ConnectorTimeoutError."""

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    transport = httpx.MockTransport(timeout_handler)
    async with httpx.AsyncClient(transport=transport) as raw_client:
        client = ExternalHttpClient(client=raw_client, max_retries=1, default_timeout=1.0)
        with pytest.raises(ConnectorTimeoutError):
            await client.get("https://api.example.com/slow")


@pytest.mark.asyncio
async def test_external_client_response_size_bounding():
    """Verify responses exceeding max_response_size are rejected."""
    huge_data = "x" * (1024 * 1024 + 50)  # > 1 MB

    def huge_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=huge_data.encode("utf-8"))

    transport = httpx.MockTransport(huge_handler)
    async with httpx.AsyncClient(transport=transport) as raw_client:
        client = ExternalHttpClient(client=raw_client, max_response_size=1024 * 1024)
        with pytest.raises(ConnectorServiceError, match="exceeds maximum permitted size"):
            await client.get("https://api.example.com/huge")
