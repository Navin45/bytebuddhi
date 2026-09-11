"""SSRF-safe HTTP fetcher built on httpx.

This is not a second generic HTTP client. ExternalHttpClient is designed for
authenticated connector APIs (JSON, auto error mapping, post-read size checks,
and no URL policy). Public page fetch requires: pre-request SSRF checks,
per-redirect validation, streaming byte limits, and textual content-type policy.
"""

from __future__ import annotations

import asyncio
from email.message import Message

import httpx

from app.application.ports.output.observability.noop import NoOpTracer
from app.application.ports.output.observability.tracer import Tracer
from app.application.web.limits import WebResearchLimits
from app.application.web.models import FetchedDocument, FetchRequest, utc_now
from app.application.web.url_policy import UrlSafetyPolicy
from app.domain.exceptions.web_exceptions import (
    ContentTooLarge,
    FetchFailed,
    FetchTimeout,
    UnsupportedContentType,
)
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)

_SUPPORTED_TEXT_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "application/json",
        "application/xml",
        "text/xml",
        "text/markdown",
        "text/csv",
        "application/javascript",
        "text/javascript",
        "application/atom+xml",
        "application/rss+xml",
    }
)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class HttpxWebFetcher:
    """Async WebFetcher adapter using httpx with follow_redirects disabled."""

    def __init__(
        self,
        url_policy: UrlSafetyPolicy,
        limits: WebResearchLimits,
        client: httpx.AsyncClient | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._url_policy = url_policy
        self._limits = limits
        self._owns_client = client is None
        timeout = httpx.Timeout(
            connect=min(10.0, limits.fetch_timeout_seconds),
            read=limits.fetch_timeout_seconds,
            write=limits.fetch_timeout_seconds,
            pool=limits.fetch_timeout_seconds,
        )
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=timeout,
            headers={
                "User-Agent": limits.user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain,application/json,application/xml;q=0.9,*/*;q=0.1",
                "Accept-Language": limits.accept_language,
            },
            max_redirects=0,
        )
        self._tracer = tracer or NoOpTracer()

    async def fetch(self, request: FetchRequest) -> FetchedDocument:
        """GET a public URL with SSRF, redirect, retry, and streaming byte limits."""
        current_url = await self._url_policy.assert_safe(request.url)
        redirect_count = 0
        max_redirects = min(request.max_redirects, self._limits.max_redirects)
        timeout = min(request.timeout_seconds, self._limits.fetch_timeout_seconds)
        max_bytes = min(request.max_response_bytes, self._limits.max_response_bytes)
        attempts = 0
        max_attempts = self._limits.max_retries

        while True:
            attempts += 1
            try:
                response = await self._client.get(
                    current_url,
                    timeout=timeout,
                    follow_redirects=False,
                    headers=self._controlled_headers(),
                )
            except httpx.TimeoutException as exc:
                if attempts < max_attempts:
                    await asyncio.sleep(self._backoff(attempts))
                    continue
                raise FetchTimeout(f"Fetch timed out after {timeout}s") from exc
            except httpx.ConnectError as exc:
                if attempts < max_attempts:
                    await asyncio.sleep(self._backoff(attempts))
                    continue
                raise FetchFailed("Connection failed") from exc
            except asyncio.CancelledError:
                raise
            except httpx.HTTPError as exc:
                raise FetchFailed("HTTP request failed") from exc

            if response.status_code in {301, 302, 303, 307, 308}:
                if redirect_count >= max_redirects:
                    await response.aclose()
                    raise FetchFailed(f"Exceeded maximum redirects ({max_redirects})")
                location = response.headers.get("Location")
                await response.aclose()
                current_url = await self._url_policy.resolve_redirect(current_url, location)
                redirect_count += 1
                attempts = 0
                continue

            if response.status_code in _RETRYABLE_STATUS:
                if attempts < max_attempts:
                    delay = self._retry_after(response) or self._backoff(attempts)
                    await response.aclose()
                    await asyncio.sleep(delay)
                    continue
                status = response.status_code
                await response.aclose()
                raise FetchFailed(f"Fetch failed with HTTP {status}")

            if response.status_code >= 400:
                status = response.status_code
                await response.aclose()
                raise FetchFailed(f"Fetch failed with HTTP {status}")

            content_type_header = response.headers.get("content-type", "text/html")
            mime, encoding = _parse_content_type(content_type_header)
            if mime and mime not in _SUPPORTED_TEXT_TYPES and not mime.startswith("text/"):
                await response.aclose()
                raise UnsupportedContentType(
                    f"Content type '{mime}' is not a supported textual type",
                    content_type=mime,
                )

            content_length = response.headers.get("content-length")
            if content_length and content_length.isdigit():
                declared = int(content_length)
                if declared > max_bytes:
                    await response.aclose()
                    raise ContentTooLarge(f"Response Content-Length {declared} exceeds max_response_bytes {max_bytes}")

            body_bytes = await self._read_bounded(response, max_bytes)
            text = _decode_body(body_bytes, encoding)
            return FetchedDocument(
                url=request.url,
                final_url=str(response.url) or current_url,
                status_code=response.status_code,
                content_type=mime or "text/html",
                encoding=encoding,
                body=text,
                raw_byte_length=len(body_bytes),
                retrieved_at=utc_now(),
                redirect_count=redirect_count,
            )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _controlled_headers(self) -> dict[str, str]:
        """Model-controlled headers are never accepted."""
        return {
            "User-Agent": self._limits.user_agent,
            "Accept": "text/html,application/xhtml+xml,text/plain,application/json,application/xml;q=0.9,*/*;q=0.1",
            "Accept-Language": self._limits.accept_language,
        }

    def _backoff(self, attempts: int) -> float:
        return float(min(2 ** (attempts - 1), self._limits.max_retry_delay_seconds))

    def _retry_after(self, response: httpx.Response) -> float | None:
        header = response.headers.get("Retry-After")
        if header and header.isdigit():
            return min(float(header), self._limits.max_retry_delay_seconds)
        return None

    async def _read_bounded(self, response: httpx.Response, max_bytes: int) -> bytes:
        """Stream the body and abort as soon as the byte limit is exceeded."""
        chunks: list[bytes] = []
        total = 0
        try:
            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ContentTooLarge(f"Response exceeded max_response_bytes {max_bytes} during streaming read")
                chunks.append(chunk)
        finally:
            await response.aclose()
        return b"".join(chunks)


def _parse_content_type(header: str) -> tuple[str, str]:
    message = Message()
    message["content-type"] = header
    mime = (message.get_content_type() or "text/html").lower()
    encoding = message.get_content_charset() or "utf-8"
    return mime, encoding


def _decode_body(body: bytes, encoding: str) -> str:
    charset = encoding or "utf-8"
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")
