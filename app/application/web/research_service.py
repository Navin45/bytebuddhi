"""Application-level web research orchestrator.

Search, fetch, extract, optional render, bound, and artifact-store. Does not
live in a tool module. Does not import concrete search/HTTP/browser libraries.
"""

from __future__ import annotations

import asyncio
import hashlib
import time

from app.application.ports.output.logger import get_logger
from app.application.ports.output.observability.meter import Meter
from app.application.ports.output.observability.noop import NoOpMeter, NoOpTracer
from app.application.ports.output.observability.tracer import SpanStatus, Tracer
from app.application.ports.output.storage.artifact_store import ArtifactStore
from app.application.ports.output.web.fetch import WebFetcher
from app.application.ports.output.web.render import WebRenderer
from app.application.ports.output.web.search import WebSearchProvider
from app.application.web.content_normalizer import normalize_extracted_markdown
from app.application.web.extractor import extract_html, extract_plain_text
from app.application.web.limits import WebResearchLimits
from app.application.web.models import (
    ExtractedContent,
    ExtractionMethod,
    FetchedDocument,
    FetchRequest,
    RenderRequest,
    ResearchBudget,
    ResearchError,
    ResearchMetadata,
    ResearchRequest,
    ResearchResult,
    ResearchSource,
    ResearchSourceStatus,
    SearchRequest,
    SearchResponse,
    SearchResult,
    utc_now,
)
from app.application.web.url_policy import UrlSafetyPolicy, canonicalize_url
from app.domain.exceptions.web_exceptions import (
    ContentTooLarge,
    FetchFailed,
    FetchTimeout,
    InvalidResearchRequest,
    PrivateAddressBlocked,
    RenderFailed,
    RenderTimeout,
    ResearchBudgetExceeded,
    ResearchCancelled,
    SearchFailed,
    UnsafeUrl,
    UnsupportedContentType,
    WebResearchError,
)
from app.domain.models.observability import MetricNames, SpanAttributes, SpanNames

logger = get_logger(__name__)


class WebResearchService:
    """Orchestrates provider-agnostic search plus safe fetch/extract/render."""

    def __init__(
        self,
        search_provider: WebSearchProvider,
        fetcher: WebFetcher,
        renderer: WebRenderer,
        url_policy: UrlSafetyPolicy,
        artifact_store: ArtifactStore,
        limits: WebResearchLimits,
        tracer: Tracer | None = None,
        meter: Meter | None = None,
    ) -> None:
        self._search = search_provider
        self._fetcher = fetcher
        self._renderer = renderer
        self._url_policy = url_policy
        self._artifacts = artifact_store
        self._limits = limits
        self._tracer = tracer or NoOpTracer()
        self._meter = meter or NoOpMeter()
        self._research_counter = self._meter.create_counter(MetricNames.WEB_RESEARCH_TOTAL)
        self._research_duration = self._meter.create_histogram(MetricNames.WEB_RESEARCH_DURATION, unit="s")
        self._search_counter = self._meter.create_counter(MetricNames.WEB_SEARCH_TOTAL)
        self._fetch_counter = self._meter.create_counter(MetricNames.WEB_FETCH_TOTAL)
        self._render_counter = self._meter.create_counter(MetricNames.WEB_RENDER_TOTAL)

    async def research(
        self,
        request: ResearchRequest,
        cancellation_token: asyncio.Event | None = None,
    ) -> ResearchResult:
        """Run bounded web research. Cancellation is propagated, not swallowed."""
        started = time.monotonic()
        self._validate_request(request)
        status = "success"
        with self._tracer.start_as_current_span(
            SpanNames.WEB_RESEARCH,
            attributes={
                SpanAttributes.WEB_PROVIDER: self._search.provider_name[:50],
            },
        ) as span:
            try:
                async with asyncio.timeout(self._limits.max_research_duration_seconds):
                    result = await self._research_inner(request, cancellation_token)
                duration = time.monotonic() - started
                result = ResearchResult(
                    query=result.query,
                    sources=result.sources,
                    errors=result.errors,
                    metadata=ResearchMetadata(
                        provider=result.metadata.provider,
                        pages_attempted=result.metadata.pages_attempted,
                        pages_succeeded=result.metadata.pages_succeeded,
                        render_fallbacks=result.metadata.render_fallbacks,
                        bytes_fetched=result.metadata.bytes_fetched,
                        content_chars=result.metadata.content_chars,
                        duration_seconds=duration,
                        search_result_count=result.metadata.search_result_count,
                    ),
                    untrusted_content_notice=result.untrusted_content_notice,
                )
                span.set_attribute(SpanAttributes.WEB_RESULT_COUNT, len(result.sources))
                span.set_attribute(SpanAttributes.WEB_PAGES_ATTEMPTED, result.metadata.pages_attempted)
                span.set_attribute(SpanAttributes.WEB_PAGES_SUCCEEDED, result.metadata.pages_succeeded)
                span.set_attribute(SpanAttributes.WEB_RENDER_FALLBACKS, result.metadata.render_fallbacks)
                span.set_attribute(SpanAttributes.WEB_BYTES_FETCHED, result.metadata.bytes_fetched)
                span.set_attribute(SpanAttributes.WEB_CONTENT_CHARS, result.metadata.content_chars)
                span.set_status(SpanStatus.OK)
                return result
            except TimeoutError as exc:
                status = "timeout"
                span.set_status(SpanStatus.ERROR, description="research budget exceeded")
                raise ResearchBudgetExceeded(
                    f"Web research exceeded {self._limits.max_research_duration_seconds}s"
                ) from exc
            except asyncio.CancelledError:
                status = "cancelled"
                span.set_status(SpanStatus.ERROR, description="cancelled")
                raise
            except ResearchCancelled:
                status = "cancelled"
                span.set_status(SpanStatus.ERROR, description="cancelled")
                raise
            except WebResearchError:
                status = "failed"
                raise
            except Exception as exc:
                status = "failed"
                span.record_exception(exc)
                span.set_status(SpanStatus.ERROR, description=type(exc).__name__)
                logger.error("Web research failed", error=str(exc), error_type=type(exc).__name__)
                raise SearchFailed("Web research failed") from exc
            finally:
                duration = time.monotonic() - started
                self._research_counter.add(
                    1,
                    {"provider_type": self._search.provider_name[:50], "execution_status": status},
                )
                self._research_duration.record(
                    duration,
                    {"provider_type": self._search.provider_name[:50], "execution_status": status},
                )

    async def aclose(self) -> None:
        """Close search, fetch, and render resources."""
        await self._search.aclose()
        await self._fetcher.aclose()
        await self._renderer.aclose()

    def _validate_request(self, request: ResearchRequest) -> None:
        query = request.query.strip() if request.query else ""
        if not query:
            raise InvalidResearchRequest("Research query must not be empty")
        if len(query) > 500:
            raise InvalidResearchRequest("Research query exceeds 500 characters")

    async def _research_inner(
        self,
        request: ResearchRequest,
        cancellation_token: asyncio.Event | None,
    ) -> ResearchResult:
        self._raise_if_cancelled(cancellation_token)
        max_results = self._limits.clamp_max_results(request.max_results)
        search_response = await self._run_search(
            SearchRequest(
                query=request.query.strip(),
                max_results=max_results,
                timeout_seconds=self._limits.search_timeout_seconds,
            )
        )
        selected = self._select_urls(search_response.results)[: self._limits.max_pages]
        if not selected:
            return ResearchResult(
                query=request.query.strip(),
                sources=(),
                errors=(
                    ResearchError(
                        code="no_accessible_results",
                        message="Search returned no accessible http(s) URLs",
                    ),
                ),
                metadata=ResearchMetadata(
                    provider=search_response.provider,
                    pages_attempted=0,
                    pages_succeeded=0,
                    render_fallbacks=0,
                    bytes_fetched=0,
                    content_chars=0,
                    duration_seconds=0.0,
                    search_result_count=len(search_response.results),
                ),
            )

        budget = ResearchBudget(
            remaining_chars=self._limits.max_total_research_chars,
            pages_remaining=len(selected),
        )
        sources = await self._fetch_selected(
            selected,
            request,
            budget,
            cancellation_token,
        )
        # Deterministic order: search rank, then original result order.
        sources.sort(key=lambda item: (item.rank, item.url))
        return ResearchResult(
            query=request.query.strip(),
            sources=tuple(sources),
            errors=tuple(budget.errors),
            metadata=ResearchMetadata(
                provider=search_response.provider,
                pages_attempted=budget.pages_attempted,
                pages_succeeded=budget.pages_succeeded,
                render_fallbacks=budget.render_fallbacks,
                bytes_fetched=budget.bytes_fetched,
                content_chars=budget.content_chars,
                duration_seconds=0.0,
                search_result_count=len(search_response.results),
            ),
        )

    async def _run_search(self, request: SearchRequest) -> SearchResponse:
        with self._tracer.start_as_current_span(
            SpanNames.WEB_SEARCH,
            attributes={SpanAttributes.WEB_PROVIDER: self._search.provider_name[:50]},
        ) as span:
            try:
                response = await self._search.search(request)
            except asyncio.CancelledError:
                raise
            except WebResearchError:
                self._search_counter.add(
                    1, {"provider_type": self._search.provider_name[:50], "execution_status": "failed"}
                )
                raise
            except Exception as exc:
                self._search_counter.add(
                    1, {"provider_type": self._search.provider_name[:50], "execution_status": "failed"}
                )
                raise SearchFailed("Search provider failed") from exc
            span.set_attribute(SpanAttributes.WEB_RESULT_COUNT, len(response.results))
            self._search_counter.add(
                1, {"provider_type": self._search.provider_name[:50], "execution_status": "success"}
            )
            return response

    def _select_urls(self, results: tuple[SearchResult, ...]) -> list[SearchResult]:
        selected: list[SearchResult] = []
        seen: set[str] = set()
        for result in results:
            canonical = canonicalize_url(result.url)
            if canonical in seen:
                continue
            parsed_scheme = canonical.split(":", 1)[0].lower()
            if parsed_scheme not in {"http", "https"}:
                continue
            seen.add(canonical)
            selected.append(result)
        return selected

    async def _fetch_selected(
        self,
        results: list[SearchResult],
        request: ResearchRequest,
        budget: ResearchBudget,
        cancellation_token: asyncio.Event | None,
    ) -> list[ResearchSource]:
        semaphore = asyncio.Semaphore(self._limits.max_concurrent_fetches)
        budget_lock = asyncio.Lock()
        indexed = list(enumerate(results))
        tasks = [
            asyncio.create_task(
                self._fetch_one(index, result, request, budget, semaphore, budget_lock, cancellation_token),
                name=f"web-fetch-{index}",
            )
            for index, result in indexed
        ]
        try:
            completed = await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        sources: list[ResearchSource] = []
        for item in completed:
            if isinstance(item, asyncio.CancelledError):
                raise item
            if isinstance(item, ResearchCancelled):
                raise item
            if isinstance(item, Exception):
                budget.errors.append(ResearchError(code="fetch_failed", message="Page fetch failed"))
                continue
            if isinstance(item, ResearchSource):
                sources.append(item)
        return sources

    async def _fetch_one(
        self,
        _index: int,
        result: SearchResult,
        request: ResearchRequest,
        budget: ResearchBudget,
        semaphore: asyncio.Semaphore,
        budget_lock: asyncio.Lock,
        cancellation_token: asyncio.Event | None,
    ) -> ResearchSource | None:
        async with semaphore:
            self._raise_if_cancelled(cancellation_token)
            async with budget_lock:
                if budget.remaining_chars <= 0:
                    return None
                budget.pages_attempted += 1
            try:
                await self._url_policy.assert_safe(result.url)
            except (UnsafeUrl, PrivateAddressBlocked) as exc:
                budget.errors.append(ResearchError(code=exc.code, message=exc.message, url=result.url))
                return ResearchSource(
                    url=result.url,
                    title=result.title,
                    retrieved_at=utc_now(),
                    content_type="",
                    status_code=None,
                    extraction_method=ExtractionMethod.UNSUPPORTED,
                    content_length=0,
                    artifact_id=None,
                    bounded_preview="",
                    rank=result.rank,
                    provider=result.provider,
                    status=ResearchSourceStatus.BLOCKED,
                    error=exc.message,
                )

            fetch_status = "success"
            with self._tracer.start_as_current_span(
                SpanNames.WEB_FETCH,
                attributes={SpanAttributes.WEB_PROVIDER: result.provider[:50]},
            ) as span:
                try:
                    document = await self._fetcher.fetch(
                        FetchRequest(
                            url=result.url,
                            timeout_seconds=self._limits.fetch_timeout_seconds,
                            max_response_bytes=self._limits.max_response_bytes,
                            max_redirects=self._limits.max_redirects,
                        )
                    )
                except asyncio.CancelledError:
                    raise
                except (UnsafeUrl, PrivateAddressBlocked) as exc:
                    fetch_status = "blocked"
                    budget.errors.append(ResearchError(code=exc.code, message=exc.message, url=result.url))
                    return self._failed_source(result, ResearchSourceStatus.BLOCKED, exc.message)
                except FetchTimeout as exc:
                    fetch_status = "timeout"
                    budget.errors.append(ResearchError(code=exc.code, message=exc.message, url=result.url))
                    return self._failed_source(result, ResearchSourceStatus.TIMEOUT, exc.message)
                except ContentTooLarge as exc:
                    fetch_status = "too_large"
                    budget.errors.append(ResearchError(code=exc.code, message=exc.message, url=result.url))
                    return self._failed_source(result, ResearchSourceStatus.TOO_LARGE, exc.message)
                except UnsupportedContentType as exc:
                    fetch_status = "unsupported"
                    budget.errors.append(ResearchError(code=exc.code, message=exc.message, url=result.url))
                    return self._failed_source(result, ResearchSourceStatus.UNSUPPORTED, exc.message)
                except (FetchFailed, WebResearchError) as exc:
                    fetch_status = "failed"
                    budget.errors.append(ResearchError(code=exc.code, message=exc.message, url=result.url))
                    return self._failed_source(result, ResearchSourceStatus.FAILED, exc.message)
                except Exception as exc:
                    fetch_status = "failed"
                    logger.error("Fetch failed", error_type=type(exc).__name__)
                    budget.errors.append(ResearchError(code="fetch_failed", message="Fetch failed", url=result.url))
                    return self._failed_source(result, ResearchSourceStatus.FAILED, "Fetch failed")
                finally:
                    self._fetch_counter.add(
                        1,
                        {
                            "provider_type": result.provider[:50],
                            "execution_status": fetch_status,
                        },
                    )

                async with budget_lock:
                    budget.bytes_fetched += document.raw_byte_length
                span.set_attribute(SpanAttributes.HTTP_STATUS, document.status_code)
                span.set_attribute(SpanAttributes.WEB_BYTES_FETCHED, document.raw_byte_length)

            extracted, used_render = await self._extract_with_optional_render(document, cancellation_token)
            async with budget_lock:
                if used_render:
                    budget.render_fallbacks += 1
                page_budget = min(self._limits.max_extracted_chars_per_page, budget.remaining_chars)
            normalized = normalize_extracted_markdown(extracted.title, extracted.markdown, page_budget)
            if not normalized.strip():
                return self._failed_source(result, ResearchSourceStatus.FAILED, "No usable content extracted")

            async with budget_lock:
                budget.remaining_chars = max(0, budget.remaining_chars - len(normalized))
                budget.content_chars += len(normalized)
                budget.pages_succeeded += 1

            artifact_id = await self._store_artifact(request, result, normalized)
            preview = normalized[: self._limits.preview_chars]
            title = extracted.title or result.title
            return ResearchSource(
                url=document.final_url or result.url,
                title=title,
                retrieved_at=document.retrieved_at,
                content_type=document.content_type,
                status_code=document.status_code,
                extraction_method=extracted.method,
                content_length=len(normalized),
                artifact_id=artifact_id,
                bounded_preview=preview,
                rank=result.rank,
                provider=result.provider,
                status=ResearchSourceStatus.SUCCESS,
            )

    async def _extract_with_optional_render(
        self,
        document: FetchedDocument,
        cancellation_token: asyncio.Event | None,
    ) -> tuple[ExtractedContent, bool]:
        with self._tracer.start_as_current_span(SpanNames.WEB_EXTRACT) as span:
            extracted = self._extract_document(document)
            usable = len(extracted.markdown.strip()) >= self._limits.min_usable_content_chars
            span.set_attribute(SpanAttributes.WEB_EXTRACTION_METHOD, extracted.method.value)
            span.set_attribute(SpanAttributes.WEB_CONTENT_CHARS, len(extracted.markdown))
            if usable or not self._renderer.enabled:
                return extracted, False

        self._raise_if_cancelled(cancellation_token)
        render_status = "success"
        with self._tracer.start_as_current_span(SpanNames.WEB_RENDER) as span:
            try:
                rendered = await self._renderer.render(
                    RenderRequest(
                        url=document.final_url or document.url,
                        timeout_seconds=self._limits.render_timeout_seconds,
                        max_content_chars=self._limits.max_extracted_chars_per_page,
                    )
                )
                html_extracted = extract_html(rendered.html, "text/html")
                html_extracted = ExtractedContent(
                    title=html_extracted.title,
                    markdown=html_extracted.markdown,
                    method=ExtractionMethod.RENDER,
                    content_type="text/html",
                )
                span.set_attribute(SpanAttributes.WEB_EXTRACTION_METHOD, ExtractionMethod.RENDER.value)
                return html_extracted, True
            except asyncio.CancelledError:
                raise
            except (RenderTimeout, RenderFailed, UnsafeUrl, PrivateAddressBlocked) as exc:
                render_status = "failed"
                logger.warning("Render fallback failed", error_type=type(exc).__name__)
                return extracted, False
            except Exception as exc:
                render_status = "failed"
                logger.warning("Render fallback failed", error_type=type(exc).__name__)
                return extracted, False
            finally:
                self._render_counter.add(
                    1,
                    {
                        "provider_type": self._search.provider_name[:50],
                        "execution_status": render_status,
                    },
                )

    def _extract_document(self, document: FetchedDocument) -> ExtractedContent:
        mime = document.content_type.split(";", 1)[0].strip().lower()
        if mime in {"text/html", "application/xhtml+xml"}:
            return extract_html(document.body, mime)
        if mime in {"application/json"}:
            return extract_plain_text(document.body, mime, ExtractionMethod.JSON)
        if mime in {"application/xml", "text/xml"}:
            return extract_plain_text(document.body, mime, ExtractionMethod.XML)
        return extract_plain_text(document.body, mime or "text/plain", ExtractionMethod.PLAIN_TEXT)

    async def _store_artifact(
        self,
        request: ResearchRequest,
        result: SearchResult,
        content: str,
    ) -> str | None:
        digest = hashlib.sha256(f"{request.run_id}:{result.url}".encode()).hexdigest()[:16]
        artifact_id = f"web_{digest}"
        try:
            await self._artifacts.save_artifact(
                artifact_id=artifact_id,
                content=content,
                metadata={
                    "tool_name": "web_research",
                    "run_id": request.run_id,
                    "project_id": request.project_id,
                    "user_id": request.user_id,
                    "source_url": result.url,
                    "untrusted": True,
                },
                project_id=request.project_id,
            )
            return artifact_id
        except Exception as exc:
            logger.warning("Failed to store web research artifact", error_type=type(exc).__name__)
            return None

    def _failed_source(
        self,
        result: SearchResult,
        status: ResearchSourceStatus,
        error: str,
    ) -> ResearchSource:
        return ResearchSource(
            url=result.url,
            title=result.title,
            retrieved_at=utc_now(),
            content_type="",
            status_code=None,
            extraction_method=ExtractionMethod.UNSUPPORTED,
            content_length=0,
            artifact_id=None,
            bounded_preview="",
            rank=result.rank,
            provider=result.provider,
            status=status,
            error=error,
        )

    def _raise_if_cancelled(self, cancellation_token: asyncio.Event | None) -> None:
        if cancellation_token is not None and cancellation_token.is_set():
            raise ResearchCancelled()
