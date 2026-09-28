"""Test protocol version compatibility between client and gateway."""

from __future__ import annotations

import httpx
import pytest

from app.interfaces.gateway.client import GatewayClient
from app.interfaces.gateway.errors import ProtocolIncompatible


@pytest.mark.asyncio
async def test_protocol_compatible_handshake():
    """Client protocol 1 and gateway protocol 1 handshake successfully."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/health/live"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "service": "ByteBuddhi Gateway",
                "version": "0.1.4-rc.1",
                "protocol_version": 1,
                "min_protocol_version": 1,
            },
        )

    transport = httpx.MockTransport(handler)
    client = GatewayClient(base_url="http://127.0.0.1:8765", transport=transport)

    health = await client.health()
    assert health.status == "ok"
    assert health.protocol_version == 1
    assert health.min_protocol_version == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_protocol_incompatible_gateway_too_new():
    """Gateway requires protocol 2, but client is protocol 1 -> fails clearly."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "service": "ByteBuddhi Gateway",
                "version": "0.2.0",
                "protocol_version": 2,
                "min_protocol_version": 2,  # requires at least 2
            },
        )

    transport = httpx.MockTransport(handler)
    client = GatewayClient(base_url="http://127.0.0.1:8765", transport=transport)

    with pytest.raises(ProtocolIncompatible) as exc_info:
        await client.health()

    assert "incompatible with gateway" in str(exc_info.value).lower()
    await client.aclose()


@pytest.mark.asyncio
async def test_protocol_incompatible_gateway_too_old():
    """Gateway reports protocol 0, below client's MIN_PROTOCOL_VERSION -> fails clearly."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "service": "ByteBuddhi Gateway",
                "version": "0.0.9",
                "protocol_version": 0,
                "min_protocol_version": 0,
            },
        )

    transport = httpx.MockTransport(handler)
    client = GatewayClient(base_url="http://127.0.0.1:8765", transport=transport)

    with pytest.raises(ProtocolIncompatible) as exc_info:
        await client.health()

    assert "too old" in str(exc_info.value).lower()
    await client.aclose()


@pytest.mark.asyncio
async def test_protocol_incompatible_does_not_corrupt_client_state():
    """When a protocol incompatibility error occurs, client remains safely closed without corrupting state."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "service": "ByteBuddhi Gateway",
                "version": "0.2.0",
                "protocol_version": 2,
                "min_protocol_version": 2,
            },
        )

    transport = httpx.MockTransport(handler)
    client = GatewayClient(base_url="http://127.0.0.1:8765", transport=transport)

    # First attempt fails cleanly
    with pytest.raises(ProtocolIncompatible):
        await client.health()

    # Second attempt also fails cleanly with no corrupted residue or deadlocks
    with pytest.raises(ProtocolIncompatible):
        await client.health()

    await client.aclose()
