"""Bounded Playwright renderer for JavaScript-heavy public pages.

Does not launch one browser per URL. Shares a single browser instance and
bounds concurrent pages. Inherits UrlSafetyPolicy for initial URLs, in-page
navigation, and subresource requests.

Known limitation: Playwright may begin a connection before route abort
completes for the very first document request. Combined with post-navigation
URL checks this reduces, but does not perfectly eliminate, DNS-rebinding risk.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from app.application.ports.output.observability.meter import Meter
from app.application.ports.output.observability.noop import NoOpMeter, NoOpTracer
from app.application.ports.output.observability.tracer import Tracer
from app.application.web.limits import WebResearchLimits
from app.application.web.models import RenderedDocument, RenderRequest, utc_now
from app.application.web.url_policy import UrlSafetyPolicy
from app.domain.exceptions.web_exceptions import RenderFailed, RenderTimeout, UnsafeUrl
from app.domain.models.observability import MetricNames, SpanAttributes
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class PlaywrightWebRenderer:
    """Shared-browser WebRenderer adapter."""

    def __init__(
        self,
        url_policy: UrlSafetyPolicy,
        limits: WebResearchLimits,
        tracer: Tracer | None = None,
        meter: Meter | None = None,
    ) -> None:
        self._url_policy = url_policy
        self._limits = limits
        self._lock = asyncio.Lock()
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._page_slots = asyncio.Semaphore(max(1, limits.max_render_pages))
        self._closed = False
        self._tracer = tracer or NoOpTracer()
        self._meter = meter or NoOpMeter()
        self._duration_hist = self._meter.create_histogram(MetricNames.BROWSER_DURATION, unit="ms")

    @property
    def enabled(self) -> bool:
        return True

    async def render(self, request: RenderRequest) -> RenderedDocument:
        if self._closed:
            raise RenderFailed("Renderer has been shut down")
        await self._url_policy.assert_safe(request.url)
        timeout_ms = int(min(request.timeout_seconds, self._limits.render_timeout_seconds) * 1000)
        started = time.perf_counter()
        status = "success"
        span = self._tracer.get_current_span()
        try:
            async with self._page_slots:
                browser = await self._ensure_browser()
                context = await browser.new_context(
                    java_script_enabled=True,
                    accept_downloads=False,
                    ignore_https_errors=False,
                    user_agent=self._limits.user_agent,
                    extra_http_headers={"Accept-Language": self._limits.accept_language},
                )
                page = None
                try:
                    page = await context.new_page()
                    page.set_default_timeout(timeout_ms)
                    page.set_default_navigation_timeout(timeout_ms)
                    page.on("download", _cancel_download)
                    await page.route("**/*", self._filter_route)
                    try:
                        async with asyncio.timeout(request.timeout_seconds):
                            await page.goto(request.url, wait_until="domcontentloaded", timeout=timeout_ms)
                            await self._url_policy.assert_safe(page.url)
                            html = await page.content()
                    except TimeoutError as exc:
                        status = "timeout"
                        raise RenderTimeout("Page render timed out") from exc
                    except asyncio.CancelledError:
                        status = "cancelled"
                        raise
                    except UnsafeUrl:
                        status = "denied"
                        raise
                    except Exception as exc:
                        status = "failed"
                        raise RenderFailed("Page render failed") from exc
                    if len(html) > request.max_content_chars * 4:
                        html = html[: request.max_content_chars * 4]
                    return RenderedDocument(
                        url=request.url,
                        final_url=page.url,
                        html=html,
                        retrieved_at=utc_now(),
                    )
                finally:
                    if page is not None:
                        await page.close()
                    await context.close()
        finally:
            duration_ms = (time.perf_counter() - started) * 1000.0
            if span is not None:
                span.set_attribute(SpanAttributes.BROWSER_STATUS, status)
            self._duration_hist.record(duration_ms, {"execution_status": status})

    async def aclose(self) -> None:
        self._closed = True
        async with self._lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    logger.warning("Failed to close Playwright browser cleanly")
                self._browser = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    logger.warning("Failed to stop Playwright driver cleanly")
                self._playwright = None

    async def _ensure_browser(self) -> Any:
        async with self._lock:
            if self._browser is not None:
                return self._browser
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise RenderFailed("Playwright is not installed") from exc
            try:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-gpu",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-extensions",
                        "--disable-background-networking",
                        "--disable-sync",
                        "--disable-translate",
                        "--disable-features=Translate,BackForwardCache",
                        "--deny-permission-prompts",
                    ],
                )
            except Exception as exc:
                if self._playwright is not None:
                    with_stop = getattr(self._playwright, "stop", None)
                    if callable(with_stop):
                        with contextlib.suppress(Exception):
                            await with_stop()
                    self._playwright = None
                raise RenderFailed("Chromium browser runtime is unavailable") from exc
            return self._browser

    async def _filter_route(self, route: Any) -> None:
        url = route.request.url
        try:
            await self._url_policy.assert_safe(url)
        except Exception:
            await route.abort()
            return
        await route.continue_()


def _cancel_download(download: Any) -> None:
    """Phase 7.6 does not provide a file-download capability."""
    cancel = getattr(download, "cancel", None)
    if callable(cancel):
        cancel()
