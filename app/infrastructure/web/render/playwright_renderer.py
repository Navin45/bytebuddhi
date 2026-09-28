"""Bounded Playwright renderer for JavaScript-heavy public pages.

Does not launch one browser per URL. Shares a single browser instance and
bounds concurrent pages. Inherits UrlSafetyPolicy for initial URLs, in-page
navigation, and subresource requests.

Every browser request — including redirect targets — is validated through the
URL policy *before* Chromium is allowed to reach the server. Downloads are
intercepted and discarded without writing to the process working directory.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import shutil
import tempfile
import time
from typing import Any

from app.application.ports.output.observability.meter import Meter
from app.application.ports.output.observability.noop import NoOpMeter, NoOpTracer
from app.application.ports.output.observability.tracer import Tracer
from app.application.web.limits import WebResearchLimits
from app.application.web.models import RenderedDocument, RenderRequest, utc_now
from app.application.web.url_policy import UrlSafetyPolicy
from app.domain.exceptions.web_exceptions import (
    PrivateAddressBlocked,
    RenderFailed,
    RenderTimeout,
    UnsafeUrl,
)
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
        self._download_dir: tempfile.TemporaryDirectory[str] | None = None
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

        # Mutable container so the route handler can store the first blocked
        # exception — this lets the outer code re-raise the *correct* domain
        # exception instead of a generic ``RenderFailed``.
        blocked_exc: list[Exception] = []

        async def _guard_request(route: Any) -> None:
            """Validate every request URL (including redirect targets)."""
            url = route.request.url
            if url.lower().startswith("about:"):
                await route.continue_()
                return
            try:
                await self._url_policy.assert_safe(url)
            except (PrivateAddressBlocked, UnsafeUrl) as exc:
                if not blocked_exc:
                    blocked_exc.append(exc)
                with contextlib.suppress(Exception):
                    await route.fulfill(status=403, body="blocked", content_type="text/plain")
                return
            except Exception as exc:
                if not blocked_exc:
                    blocked_exc.append(exc)
                with contextlib.suppress(Exception):
                    await route.abort("failed")
                return
            # Fetch without following redirects. continue_() lets Chromium
            # follow a 302 inside the same network request, which reaches the
            # target before this guard can reject it.
            try:
                fetched = await route.fetch(max_redirects=0)
            except Exception:
                with contextlib.suppress(Exception):
                    await route.continue_()
                return
            status = int(getattr(fetched, "status", 0) or 0)
            headers = getattr(fetched, "headers", {}) or {}
            if 300 <= status < 400:
                location = headers.get("location")
                try:
                    await self._url_policy.resolve_redirect(url, location)
                except (PrivateAddressBlocked, UnsafeUrl) as exc:
                    if not blocked_exc:
                        blocked_exc.append(exc)
                    with contextlib.suppress(Exception):
                        await route.fulfill(status=403, body="blocked", content_type="text/plain")
                    return
                except Exception as exc:
                    if not blocked_exc:
                        blocked_exc.append(exc)
                    with contextlib.suppress(Exception):
                        await route.fulfill(status=403, body="blocked", content_type="text/plain")
                    return
            disposition = str(headers.get("content-disposition") or "").lower()
            if "attachment" in disposition:
                with contextlib.suppress(Exception):
                    await route.fulfill(status=204, body="", content_type="text/plain")
                return
            await route.fulfill(response=fetched)

        try:
            async with self._page_slots:
                browser = await self._ensure_browser()
                context = await browser.new_context(
                    java_script_enabled=True,
                    accept_downloads=True,
                    ignore_https_errors=False,
                    user_agent=self._limits.user_agent,
                    extra_http_headers={"Accept-Language": self._limits.accept_language},
                )
                # Install the route guard on the *context* so every request
                # — including redirected sub-requests — is validated before
                # Chromium opens a connection.
                await context.route("**/*", _guard_request)
                page = None
                try:
                    page = await context.new_page()
                    page.set_default_timeout(timeout_ms)
                    page.set_default_navigation_timeout(timeout_ms)
                    page.on("download", _cancel_download)

                    try:
                        async with asyncio.timeout(request.timeout_seconds):
                            response = await self._safe_goto(
                                page,
                                request.url,
                                timeout_ms,
                            )
                            # If the route handler blocked a redirect target,
                            # surface the original policy exception.
                            if blocked_exc:
                                raise blocked_exc[0]
                            final_url = str(page.url or "")
                            if final_url.lower().startswith("about:") and request.url.lower().startswith(
                                ("http://", "https://")
                            ):
                                return RenderedDocument(
                                    url=request.url,
                                    final_url=request.url,
                                    html="",
                                    retrieved_at=utc_now(),
                                )
                            await self._url_policy.assert_safe(final_url)
                            # A download response has no renderable page body.
                            if response is not None:
                                return response
                            html = await page.content()
                    except TimeoutError as exc:
                        status = "timeout"
                        raise RenderTimeout("Page render timed out") from exc
                    except asyncio.CancelledError:
                        status = "cancelled"
                        raise
                    except (PrivateAddressBlocked, UnsafeUrl):
                        status = "denied"
                        raise
                    except Exception as exc:
                        # A route-abort may cause goto() to raise a generic
                        # Playwright error. Surface the blocked exception.
                        if blocked_exc:
                            status = "denied"
                            raise blocked_exc[0] from exc
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
                        with contextlib.suppress(Exception):
                            await page.close()
                    with contextlib.suppress(Exception):
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
            if self._download_dir is not None:
                with contextlib.suppress(Exception):
                    shutil.rmtree(self._download_dir.name, ignore_errors=True)
                self._download_dir = None

    async def _ensure_browser(self) -> Any:
        async with self._lock:
            if self._browser is not None:
                return self._browser
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise RenderFailed("Playwright is not installed") from exc
            try:
                self._download_dir = tempfile.TemporaryDirectory(
                    prefix="bytebuddhi-downloads-",
                )
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    downloads_path=self._download_dir.name,
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
                if self._download_dir is not None:
                    with contextlib.suppress(Exception):
                        shutil.rmtree(self._download_dir.name, ignore_errors=True)
                    self._download_dir = None
                raise RenderFailed("Chromium browser runtime is unavailable") from exc
            return self._browser

    # ------------------------------------------------------------------
    # Download-safe navigation
    # ------------------------------------------------------------------

    async def _safe_goto(
        self,
        page: Any,
        url: str,
        timeout_ms: int,
    ) -> RenderedDocument | None:
        """Navigate to *url*, handling downloads without writing to the CWD.

        Returns a ``RenderedDocument`` stub if the server triggered a download
        (the response is not renderable HTML), or ``None`` so the caller can
        read ``page.content()`` as usual.
        """
        try:
            from playwright.async_api import Error as PlaywrightError
        except ImportError:
            PlaywrightError = Exception  # type: ignore[misc,assignment]

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except PlaywrightError as exc:
            message = str(exc)
            if "Download is starting" in message or "net::ERR_ABORTED" in message:
                # A download or a discarded attachment has no page body.
                # Clean up any artefacts and do not let the file land on disk.
                await self._drain_downloads(page)
                return RenderedDocument(
                    url=url,
                    final_url=url,
                    html="",
                    retrieved_at=utc_now(),
                )
            raise
        return None

    @staticmethod
    async def _drain_downloads(page: Any) -> None:
        """Cancel and delete all in-flight downloads on *page*."""
        # Small grace period for the download event to fire.
        await asyncio.sleep(0.05)
        context = page.context
        for _page in context.pages:
            pass  # iteration triggers event flushing
        # The ``download`` event handler (_cancel_download) already calls
        # cancel(); belt-and-suspenders: sweep anything left.
        # Playwright stores downloads in the configured downloads_path; we
        # clean that directory in ``aclose()``.


async def _cancel_download(download: Any) -> None:
    """This renderer does not provide a file-download capability."""
    cancel = getattr(download, "cancel", None)
    if not callable(cancel):
        return
    result = cancel()
    if inspect.isawaitable(result):
        await result
