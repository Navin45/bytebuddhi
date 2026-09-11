"""External HTTP client with connection management, retry safety, and header sanitization."""

import asyncio
import json as json_module
from typing import Any

import httpx

from app.application.ports.output.observability.meter import Counter, Histogram, Meter
from app.application.ports.output.observability.tracer import Tracer
from app.domain.exceptions.connector_exceptions import (
    ConnectorAuthenticationError,
    ConnectorAuthorizationError,
    ConnectorError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    ConnectorServiceError,
    ConnectorTimeoutError,
)
from app.domain.models.observability import MetricNames, SpanAttributes, SpanNames
from app.infrastructure.config.logger import get_logger
from app.infrastructure.observability.noop import NoOpMeter, NoOpTracer

logger = get_logger(__name__)


class ExternalResponseDict(dict):
    """Wrapper that behaves as a dict while exposing status_code, headers, and .json()."""

    def __init__(self, data: dict[str, Any], status_code: int = 200, headers: dict[str, str] | None = None) -> None:
        super().__init__(data)
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> Any:
        return dict(self)


class ExternalResponseList(list):
    """Wrapper that behaves as a list while exposing status_code, headers, and .json()."""

    def __init__(self, data: list[Any], status_code: int = 200, headers: dict[str, str] | None = None) -> None:
        super().__init__(data)
        self.status_code = status_code
        self.headers = headers or {}

    def json(self) -> Any:
        return list(self)


class ExternalResponseText(str):
    """Wrapper that behaves as a string while exposing status_code, headers, and .json()."""

    status_code: int
    headers: dict[str, str]

    def __new__(
        cls, content: str, status_code: int = 200, headers: dict[str, str] | None = None
    ) -> "ExternalResponseText":
        instance = super().__new__(cls, content)
        instance.status_code = status_code
        instance.headers = headers or {}
        return instance

    def json(self) -> Any:
        return json_module.loads(self)


class ExternalHttpClient:
    """Canonical bounded HTTP client for external service connectors."""

    SAFE_IDEMPOTENT_METHODS: set[str] = {"GET", "HEAD", "OPTIONS"}

    def __init__(
        self,
        default_timeout: float = 15.0,
        max_response_bytes: int = 1_000_000,
        max_retries: int = 3,
        max_retry_delay: float = 10.0,
        client: httpx.AsyncClient | None = None,
        max_response_size: int | None = None,
        tracer: Tracer | None = None,
        meter: Meter | None = None,
    ) -> None:
        self.default_timeout = default_timeout
        self.max_response_bytes = max_response_size if max_response_size is not None else max_response_bytes
        self.max_retries = max_retries
        self.max_retry_delay = max_retry_delay
        self._client = client or httpx.AsyncClient(timeout=default_timeout)
        self.tracer = tracer or NoOpTracer()
        self.meter = meter or NoOpMeter()
        self._requests_counter: Counter = self.meter.create_counter(
            MetricNames.CONNECTOR_REQUESTS_TOTAL,
            unit="1",
            description="Total external connector HTTP requests",
        )
        self._failures_counter: Counter = self.meter.create_counter(
            MetricNames.CONNECTOR_FAILURES_TOTAL,
            unit="1",
            description="Total external connector HTTP failures",
        )
        self._duration_hist: Histogram = self.meter.create_histogram(
            MetricNames.CONNECTOR_DURATION,
            unit="s",
            description="External connector request duration in seconds",
        )

    @staticmethod
    def sanitize_headers(headers: dict[str, str] | None) -> dict[str, str]:
        """Redact sensitive authorization and secret tokens from header mappings."""
        if not headers:
            return {}
        sanitized = {}
        for k, v in headers.items():
            if k.lower() in ("authorization", "x-api-key", "token", "secret", "cookie"):
                sanitized[k] = "******"
            else:
                sanitized[k] = v
        return sanitized

    async def get(
        self,
        url: str,
        provider: str = "external",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Perform GET request."""
        return await self.request(
            method="GET",
            url=url,
            provider=provider,
            headers=headers,
            params=params,
            timeout=timeout,
        )

    async def post(
        self,
        url: str,
        provider: str = "external",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_data: Any | None = None,
        json: Any | None = None,
        timeout: float | None = None,
        allow_mutation_retry: bool = False,
    ) -> Any:
        """Perform POST request."""
        body = json if json is not None else json_data
        return await self.request(
            method="POST",
            url=url,
            provider=provider,
            headers=headers,
            params=params,
            json=body,
            timeout=timeout,
            allow_mutation_retry=allow_mutation_retry,
        )

    async def put(
        self,
        url: str,
        provider: str = "external",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_data: Any | None = None,
        json: Any | None = None,
        timeout: float | None = None,
        allow_mutation_retry: bool = False,
    ) -> Any:
        """Perform PUT request."""
        body = json if json is not None else json_data
        return await self.request(
            method="PUT",
            url=url,
            provider=provider,
            headers=headers,
            params=params,
            json=body,
            timeout=timeout,
            allow_mutation_retry=allow_mutation_retry,
        )

    async def delete(
        self,
        url: str,
        provider: str = "external",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Perform DELETE request."""
        return await self.request(
            method="DELETE",
            url=url,
            provider=provider,
            headers=headers,
            params=params,
            timeout=timeout,
        )

    async def request(
        self,
        method: str,
        url: str,
        provider: str = "external",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        timeout: float | None = None,
        allow_mutation_retry: bool = False,
    ) -> Any:
        """Perform external HTTP request with retry, bounding, and error normalization.

        Retry Invariant:
            Only idempotent methods (GET/HEAD) or requests with allow_mutation_retry=True
            are retried. Mutating operations (POST/PUT/DELETE) are never retried blindly.
        """
        import time

        start_time = time.monotonic()
        method_upper = method.upper().strip()
        is_idempotent = method_upper in self.SAFE_IDEMPOTENT_METHODS or allow_mutation_retry
        req_timeout = timeout or self.default_timeout

        with self.tracer.start_as_current_span(
            SpanNames.CONNECTOR_REQUEST,
            attributes={
                SpanAttributes.CONNECTOR_TYPE: provider[:50],
                SpanAttributes.CONNECTOR_OPERATION: method_upper,
            },
        ) as span:
            self._requests_counter.add(1, {"connector_type": provider[:50]})
            attempts = 0
            try:
                while attempts < self.max_retries:
                    attempts += 1
                    try:
                        resp = await self._client.request(
                            method=method_upper,
                            url=url,
                            headers=headers,
                            params=params,
                            json=json,
                            timeout=req_timeout,
                        )
                        span.set_attribute(SpanAttributes.HTTP_STATUS, resp.status_code)
                        span.set_attribute(SpanAttributes.RETRY_COUNT, attempts - 1)

                        # Status code mapping & retry logic
                        if resp.status_code == 429:
                            retry_after_str = resp.headers.get("Retry-After")
                            actual_retry_after: float | None = None
                            if retry_after_str and retry_after_str.isdigit():
                                actual_retry_after = float(retry_after_str)

                            if is_idempotent and attempts < self.max_retries:
                                backoff = (
                                    min(actual_retry_after, self.max_retry_delay)
                                    if actual_retry_after is not None
                                    else min(2 ** (attempts - 1), self.max_retry_delay)
                                )
                                logger.warning(
                                    "HTTP 429 rate limit received, backing off", provider=provider, wait=backoff
                                )
                                await asyncio.sleep(backoff)
                                continue

                            raise ConnectorRateLimitError(
                                f"Rate limit exceeded on {provider} API",
                                provider=provider,
                                retry_after=actual_retry_after,
                            )

                        if resp.status_code >= 500:
                            if is_idempotent and attempts < self.max_retries:
                                backoff = min(2 ** (attempts - 1), self.max_retry_delay)
                                logger.warning(
                                    "HTTP 5xx server error, retrying", provider=provider, status=resp.status_code
                                )
                                await asyncio.sleep(backoff)
                                continue
                            raise ConnectorServiceError(
                                f"Service error {resp.status_code} from {provider}",
                                provider=provider,
                                status_code=resp.status_code,
                            )

                        if resp.status_code == 401:
                            raise ConnectorAuthenticationError(
                                f"Authentication failed for {provider}: check credentials",
                                provider=provider,
                                status_code=401,
                            )

                        if resp.status_code == 403:
                            raise ConnectorAuthorizationError(
                                f"Permission denied for {provider}: operation forbidden",
                                provider=provider,
                                status_code=403,
                            )

                        if resp.status_code == 404:
                            raise ConnectorNotFoundError(
                                f"Resource not found on {provider} (404)",
                                provider=provider,
                                status_code=404,
                            )

                        if resp.status_code >= 400:
                            raise ConnectorError(
                                f"Request failed with status {resp.status_code} from {provider}",
                                provider=provider,
                                status_code=resp.status_code,
                            )

                        # Read and bound body
                        content_bytes = await resp.aread()
                        if len(content_bytes) > self.max_response_bytes:
                            raise ConnectorServiceError(
                                f"Response size ({len(content_bytes)} bytes) exceeds maximum permitted size ({self.max_response_bytes} bytes)",
                                provider=provider,
                                status_code=resp.status_code,
                            )

                        content_type = resp.headers.get("content-type", "")
                        if "application/json" in content_type:
                            parsed_json = resp.json()
                            if isinstance(parsed_json, dict):
                                return ExternalResponseDict(
                                    parsed_json, status_code=resp.status_code, headers=dict(resp.headers)
                                )
                            if isinstance(parsed_json, list):
                                return ExternalResponseList(
                                    parsed_json, status_code=resp.status_code, headers=dict(resp.headers)
                                )
                            return parsed_json

                        decoded_str = content_bytes.decode("utf-8", errors="replace")
                        return ExternalResponseText(
                            decoded_str, status_code=resp.status_code, headers=dict(resp.headers)
                        )

                    except (httpx.TimeoutException, TimeoutError) as te:
                        if is_idempotent and attempts < self.max_retries:
                            await asyncio.sleep(min(2 ** (attempts - 1), self.max_retry_delay))
                            continue
                        raise ConnectorTimeoutError(
                            f"Request to {provider} timed out after {req_timeout}s",
                            provider=provider,
                        ) from te
                    except httpx.ConnectError as ce:
                        if is_idempotent and attempts < self.max_retries:
                            await asyncio.sleep(min(2 ** (attempts - 1), self.max_retry_delay))
                            continue
                        raise ConnectorServiceError(
                            f"Connection failed to {provider}: {ce!s}",
                            provider=provider,
                        ) from ce

                raise ConnectorError(f"Maximum retries ({self.max_retries}) exceeded for {provider}", provider=provider)
            except Exception:
                self._failures_counter.add(1, {"connector_type": provider[:50]})
                raise
            finally:
                duration = time.monotonic() - start_time
                self._duration_hist.record(duration, {"connector_type": provider[:50]})

    async def close(self) -> None:
        """Close underlying HTTP client connection pool."""
        await self._client.aclose()
