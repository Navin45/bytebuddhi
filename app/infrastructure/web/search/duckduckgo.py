"""DuckDuckGo HTML search adapter.

Implements WebSearchProvider. Application code must never import this class.
The HTML endpoint is a known public search URL, not an untrusted user URL.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.application.web.limits import WebResearchLimits
from app.application.web.models import SearchRequest, SearchResponse, SearchResult
from app.domain.exceptions.web_exceptions import SearchFailed
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_ENDPOINT = "https://html.duckduckgo.com/html/"

_RESULT_RE = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")


class DuckDuckGoSearchProvider:
    """Async HTML search adapter for DuckDuckGo."""

    def __init__(
        self,
        limits: WebResearchLimits,
        client: httpx.AsyncClient | None = None,
        endpoint: str | None = None,
    ) -> None:
        self._limits = limits
        self._endpoint = (endpoint or limits.search_endpoint or _DEFAULT_ENDPOINT).rstrip("/") + "/"
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(limits.search_timeout_seconds),
            headers={"User-Agent": limits.user_agent},
        )

    @property
    def provider_name(self) -> str:
        return "duckduckgo"

    async def search(self, request: SearchRequest) -> SearchResponse:
        query = request.query.strip()
        if not query:
            raise SearchFailed("Search query must not be empty")
        max_results = min(request.max_results, self._limits.max_search_results)
        timeout = min(request.timeout_seconds, self._limits.search_timeout_seconds)
        attempts = 0
        last_error: Exception | None = None
        while attempts < self._limits.max_retries:
            attempts += 1
            try:
                response = await self._client.post(
                    self._endpoint,
                    data={"q": query, "b": "", "kl": "us-en"},
                    timeout=timeout,
                    headers={
                        "User-Agent": self._limits.user_agent,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
                if response.status_code == 429 and attempts < self._limits.max_retries:
                    retry_after = response.headers.get("Retry-After")
                    delay = (
                        min(float(retry_after), self._limits.max_retry_delay_seconds)
                        if retry_after and retry_after.isdigit()
                        else min(2 ** (attempts - 1), self._limits.max_retry_delay_seconds)
                    )
                    await asyncio.sleep(delay)
                    continue
                if response.status_code >= 500 and attempts < self._limits.max_retries:
                    await asyncio.sleep(min(2 ** (attempts - 1), self._limits.max_retry_delay_seconds))
                    continue
                if response.status_code >= 400:
                    raise SearchFailed(f"Search provider returned HTTP {response.status_code}")
                results = _parse_results(response.text, max_results, self.provider_name)
                return SearchResponse(query=query, provider=self.provider_name, results=tuple(results))
            except asyncio.CancelledError:
                raise
            except SearchFailed:
                raise
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempts < self._limits.max_retries:
                    await asyncio.sleep(min(2 ** (attempts - 1), self._limits.max_retry_delay_seconds))
                    continue
                raise SearchFailed("Search timed out") from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempts < self._limits.max_retries:
                    await asyncio.sleep(min(2 ** (attempts - 1), self._limits.max_retry_delay_seconds))
                    continue
                raise SearchFailed("Search provider request failed") from exc
        raise SearchFailed("Search provider failed") from last_error

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _parse_results(html: str, max_results: int, provider: str) -> list[SearchResult]:
    matches = list(_RESULT_RE.finditer(html))
    snippets = [_clean_html(match.group(1)) for match in _SNIPPET_RE.finditer(html)]
    results: list[SearchResult] = []
    for index, match in enumerate(matches):
        if len(results) >= max_results:
            break
        href = _unwrap_ddg_url(html_lib.unescape(match.group(1)))
        title = _clean_html(match.group(2))
        if not href:
            continue
        snippet = snippets[index] if index < len(snippets) else ""
        results.append(
            SearchResult(
                title=title or href,
                url=href,
                snippet=snippet,
                rank=len(results) + 1,
                provider=provider,
            )
        )
    return results


def _clean_html(value: str) -> str:
    return " ".join(_TAG_RE.sub("", html_lib.unescape(value)).split())


def _unwrap_ddg_url(href: str) -> str:
    parsed = urlparse(href)
    if parsed.path.endswith("/l/") or "duckduckgo.com/l/" in href:
        uddg = parse_qs(parsed.query).get("uddg", [])
        if uddg:
            return unquote(uddg[0])
    return href
