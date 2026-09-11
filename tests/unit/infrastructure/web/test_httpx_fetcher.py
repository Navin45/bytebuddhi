"""HttpxWebFetcher SSRF, redirect, streaming bounds, retries, and decoding tests."""

import gzip

import httpx
import pytest

from app.application.web.limits import WebResearchLimits
from app.application.web.models import FetchRequest
from app.application.web.url_policy import UrlSafetyPolicy
from app.domain.exceptions.web_exceptions import (
    ContentTooLarge,
    FetchFailed,
    FetchTimeout,
    PrivateAddressBlocked,
    UnsupportedContentType,
)
from app.infrastructure.web.fetch.httpx_fetcher import HttpxWebFetcher
from tests.fixtures.web.fakes import StaticResolver

PUBLIC = "https://public.example/page"
PUBLIC_HOST = "public.example"


def _fetcher(handler, limits: WebResearchLimits | None = None) -> HttpxWebFetcher:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, follow_redirects=False)
    policy = UrlSafetyPolicy(resolver=StaticResolver({PUBLIC_HOST: ("8.8.8.8",)}))
    return HttpxWebFetcher(
        url_policy=policy,
        limits=limits or WebResearchLimits(max_retries=3, max_retry_delay_seconds=0.01),
        client=client,
    )


def _req(**kwargs) -> FetchRequest:
    values = {
        "url": PUBLIC,
        "timeout_seconds": 5.0,
        "max_response_bytes": 10_000,
        "max_redirects": 3,
    }
    values.update(kwargs)
    return FetchRequest(**values)


@pytest.mark.asyncio
async def test_fetch_html_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><p>hi</p></html>", headers={"content-type": "text/html"})

    fetcher = _fetcher(handler)
    doc = await fetcher.fetch(_req())
    assert doc.status_code == 200
    assert "hi" in doc.body
    await fetcher.aclose()


@pytest.mark.asyncio
async def test_redirect_to_loopback_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})

    fetcher = _fetcher(handler)
    with pytest.raises(PrivateAddressBlocked):
        await fetcher.fetch(_req())
    await fetcher.aclose()


@pytest.mark.asyncio
async def test_oversized_content_length_rejected_before_read() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"abc",
            headers={"content-type": "text/plain", "content-length": "999999"},
        )

    fetcher = _fetcher(handler, WebResearchLimits(max_response_bytes=100, max_retries=1))
    with pytest.raises(ContentTooLarge):
        await fetcher.fetch(_req(max_response_bytes=100))
    await fetcher.aclose()


@pytest.mark.asyncio
async def test_streaming_read_aborts_when_over_byte_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"x" * 5000,
            headers={"content-type": "text/plain"},
        )

    fetcher = _fetcher(handler, WebResearchLimits(max_response_bytes=100, max_retries=1))
    with pytest.raises(ContentTooLarge):
        await fetcher.fetch(_req(max_response_bytes=100))
    await fetcher.aclose()


@pytest.mark.asyncio
async def test_binary_content_type_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x00\x01", headers={"content-type": "application/octet-stream"})

    fetcher = _fetcher(handler)
    with pytest.raises(UnsupportedContentType):
        await fetcher.fetch(_req())
    await fetcher.aclose()


@pytest.mark.asyncio
async def test_gzip_response_decoded() -> None:
    payload = gzip.compress(b"<html><p>gzipped</p></html>")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "text/html", "content-encoding": "gzip"},
        )

    fetcher = _fetcher(handler)
    doc = await fetcher.fetch(_req())
    assert "gzipped" in doc.body
    await fetcher.aclose()


@pytest.mark.asyncio
async def test_invalid_encoding_replaced() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"caf\xe9",
            headers={"content-type": "text/plain; charset=utf-8"},
        )

    fetcher = _fetcher(handler)
    doc = await fetcher.fetch(_req())
    assert "caf" in doc.body
    await fetcher.aclose()


@pytest.mark.asyncio
async def test_retry_on_500_then_success() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(500, text="nope")
        return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})

    fetcher = _fetcher(handler, WebResearchLimits(max_retries=3, max_retry_delay_seconds=0.01))
    doc = await fetcher.fetch(_req())
    assert doc.body == "ok"
    assert calls["n"] == 2
    await fetcher.aclose()


@pytest.mark.asyncio
async def test_429_honors_retry_after() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})

    fetcher = _fetcher(handler, WebResearchLimits(max_retries=3, max_retry_delay_seconds=1.0))
    doc = await fetcher.fetch(_req())
    assert doc.body == "ok"
    await fetcher.aclose()


@pytest.mark.asyncio
async def test_timeout_maps_to_fetch_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    fetcher = _fetcher(handler, WebResearchLimits(max_retries=1))
    with pytest.raises(FetchTimeout):
        await fetcher.fetch(_req(timeout_seconds=0.1))
    await fetcher.aclose()


@pytest.mark.asyncio
async def test_http_404_is_fetch_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="missing")

    fetcher = _fetcher(handler, WebResearchLimits(max_retries=1))
    with pytest.raises(FetchFailed):
        await fetcher.fetch(_req())
    await fetcher.aclose()
