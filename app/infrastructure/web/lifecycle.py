"""Lifecycle-managed web research resources.

Shared HTTP and browser resources must outlive a single FastAPI request so
Playwright does not launch a browser per call and HTTP pools stay bounded.
"""

from dataclasses import dataclass

from app.application.ports.output.observability.meter import Meter
from app.application.ports.output.observability.tracer import Tracer
from app.application.ports.output.storage.artifact_store import ArtifactStore
from app.application.web.limits import WebResearchLimits
from app.application.web.research_service import WebResearchService
from app.application.web.url_policy import HostnameResolver, UrlSafetyPolicy
from app.infrastructure.config.logger import get_logger
from app.infrastructure.web.fetch.httpx_fetcher import HttpxWebFetcher
from app.infrastructure.web.render.noop import NoOpWebRenderer
from app.infrastructure.web.search.duckduckgo import DuckDuckGoSearchProvider

logger = get_logger(__name__)

_resources: "WebResearchResources | None" = None


@dataclass
class WebResearchResources:
    """Owned web research stack with explicit shutdown."""

    service: WebResearchService
    limits: WebResearchLimits

    async def aclose(self) -> None:
        await self.service.aclose()


def limits_from_settings(settings: object) -> WebResearchLimits:
    """Map infrastructure Settings fields onto application-owned limits."""
    return WebResearchLimits(
        max_search_results=int(getattr(settings, "web_search_max_results", 5)),
        max_pages=int(getattr(settings, "web_research_max_pages", 5)),
        max_concurrent_fetches=int(getattr(settings, "web_research_max_concurrent_fetches", 4)),
        max_response_bytes=int(getattr(settings, "web_fetch_max_response_bytes", 1_000_000)),
        max_extracted_chars_per_page=int(getattr(settings, "web_research_max_extracted_chars", 10_000)),
        max_total_research_chars=int(getattr(settings, "web_research_max_total_chars", 30_000)),
        max_research_duration_seconds=float(getattr(settings, "web_research_max_duration_seconds", 30.0)),
        search_timeout_seconds=float(getattr(settings, "web_search_timeout_seconds", 10.0)),
        fetch_timeout_seconds=float(getattr(settings, "web_fetch_timeout_seconds", 15.0)),
        render_timeout_seconds=float(getattr(settings, "web_render_timeout_seconds", 20.0)),
        max_redirects=int(getattr(settings, "web_fetch_max_redirects", 5)),
        max_retries=int(getattr(settings, "web_fetch_max_retries", 3)),
        preview_chars=int(getattr(settings, "web_research_preview_chars", 800)),
        render_enabled=bool(getattr(settings, "web_render_enabled", False)),
        max_browser_instances=int(getattr(settings, "web_render_max_browser_instances", 1)),
        max_render_pages=int(getattr(settings, "web_render_max_pages", 2)),
        user_agent=str(getattr(settings, "web_user_agent", WebResearchLimits.user_agent)),
        provider_name=str(getattr(settings, "web_search_provider", "duckduckgo")),
        search_endpoint=str(getattr(settings, "web_search_endpoint", "https://html.duckduckgo.com/html/")),
    )


def build_web_research_service(
    settings: object,
    artifact_store: ArtifactStore,
    tracer: Tracer | None = None,
    meter: Meter | None = None,
) -> WebResearchService:
    """Compose application service from infrastructure adapters."""
    limits = limits_from_settings(settings)
    policy = UrlSafetyPolicy(resolver=HostnameResolver())
    fetcher = HttpxWebFetcher(url_policy=policy, limits=limits, tracer=tracer)
    search = DuckDuckGoSearchProvider(limits=limits)
    if limits.render_enabled:
        from app.infrastructure.web.render.playwright_renderer import PlaywrightWebRenderer

        renderer: object = PlaywrightWebRenderer(
            url_policy=policy,
            limits=limits,
            tracer=tracer,
            meter=meter,
        )
    else:
        renderer = NoOpWebRenderer()
    return WebResearchService(
        search_provider=search,
        fetcher=fetcher,
        renderer=renderer,  # type: ignore[arg-type]
        url_policy=policy,
        artifact_store=artifact_store,
        limits=limits,
        tracer=tracer,
        meter=meter,
    )


def get_web_research_resources(
    settings: object,
    artifact_store: ArtifactStore,
    tracer: Tracer | None = None,
    meter: Meter | None = None,
) -> WebResearchResources:
    """Return the process-wide web research stack, creating it on first use."""
    global _resources
    if _resources is None:
        service = build_web_research_service(settings, artifact_store, tracer, meter)
        _resources = WebResearchResources(service=service, limits=limits_from_settings(settings))
        logger.info(
            "Web research resources initialized",
            provider=_resources.limits.provider_name,
            render_enabled=_resources.limits.render_enabled,
        )
    return _resources


async def close_web_research_resources() -> None:
    """Release HTTP sessions and browser processes."""
    global _resources
    if _resources is not None:
        await _resources.aclose()
        _resources = None
        logger.info("Web research resources closed")


def reset_web_research_resources() -> None:
    """Test helper to drop the process-wide stack without awaiting close."""
    global _resources
    _resources = None
