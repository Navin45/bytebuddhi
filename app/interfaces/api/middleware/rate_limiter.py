"""Rate limiting middleware for FastAPI.

Process-local in-memory limiter. Each worker process has independent counters;
this is not distributed rate limiting. Do not treat X-Forwarded-For as client
identity unless the direct peer is in TRUSTED_PROXY_IPS.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-process rate limiter keyed by client IP.

    Lifetime: application-scoped middleware instance per worker.
    State is not shared across Gunicorn/Uvicorn workers or hosts.
    """

    def __init__(self, app):
        super().__init__(app)
        self.rate_limit_per_minute = settings.rate_limit_per_minute
        self.rate_limit_per_hour = settings.rate_limit_per_hour
        self._trusted_proxies = {ip.strip() for ip in settings.trusted_proxy_ips if ip.strip()}
        self.request_counts: dict[str, dict[str, list[datetime]]] = defaultdict(lambda: {"minute": [], "hour": []})

    async def dispatch(self, request: Request, call_next):
        if request.url.path in {
            "/",
            "/health",
            "/api/v1/health",
            "/api/v1/health/live",
            "/api/v1/health/ready",
            "/api/v1/health/db",
            "/api/docs",
            "/api/redoc",
        }:
            return await call_next(request)

        client_ip = self._get_client_ip(request)

        try:
            self._check_rate_limit(client_ip)
        except HTTPException:
            logger.warning(
                "Rate limit exceeded",
                ip=client_ip,
                path=request.url.path,
            )
            raise

        self._record_request(client_ip)
        self._cleanup_old_entries(client_ip)

        response = await call_next(request)

        remaining_minute, remaining_hour = self._get_remaining_requests(client_ip)
        response.headers["X-RateLimit-Limit-Minute"] = str(self.rate_limit_per_minute)
        response.headers["X-RateLimit-Limit-Hour"] = str(self.rate_limit_per_hour)
        response.headers["X-RateLimit-Remaining-Minute"] = str(remaining_minute)
        response.headers["X-RateLimit-Remaining-Hour"] = str(remaining_hour)

        return response

    def _get_client_ip(self, request: Request) -> str:
        """Use the direct peer address unless that peer is a configured trusted proxy."""
        peer = request.client.host if request.client else "unknown"
        if not self._trusted_proxies or peer not in self._trusted_proxies:
            return peer
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return peer

    def _check_rate_limit(self, client_ip: str) -> None:
        now = datetime.now(UTC)
        counts = self.request_counts[client_ip]

        minute_ago = now - timedelta(minutes=1)
        minute_requests = sum(1 for timestamp in counts["minute"] if timestamp > minute_ago)

        if minute_requests >= self.rate_limit_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {self.rate_limit_per_minute} requests per minute",
                headers={"Retry-After": "60"},
            )

        hour_ago = now - timedelta(hours=1)
        hour_requests = sum(1 for timestamp in counts["hour"] if timestamp > hour_ago)

        if hour_requests >= self.rate_limit_per_hour:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {self.rate_limit_per_hour} requests per hour",
                headers={"Retry-After": "3600"},
            )

    def _record_request(self, client_ip: str) -> None:
        now = datetime.now(UTC)
        counts = self.request_counts[client_ip]
        counts["minute"].append(now)
        counts["hour"].append(now)

    def _cleanup_old_entries(self, client_ip: str) -> None:
        now = datetime.now(UTC)
        counts = self.request_counts[client_ip]

        minute_ago = now - timedelta(minutes=1)
        counts["minute"] = [timestamp for timestamp in counts["minute"] if timestamp > minute_ago]

        hour_ago = now - timedelta(hours=1)
        counts["hour"] = [timestamp for timestamp in counts["hour"] if timestamp > hour_ago]

        if not counts["minute"] and not counts["hour"]:
            del self.request_counts[client_ip]

    def _get_remaining_requests(self, client_ip: str) -> tuple[int, int]:
        now = datetime.now(UTC)
        counts = self.request_counts[client_ip]

        minute_ago = now - timedelta(minutes=1)
        minute_requests = sum(1 for timestamp in counts["minute"] if timestamp > minute_ago)

        hour_ago = now - timedelta(hours=1)
        hour_requests = sum(1 for timestamp in counts["hour"] if timestamp > hour_ago)

        remaining_minute = max(0, self.rate_limit_per_minute - minute_requests)
        remaining_hour = max(0, self.rate_limit_per_hour - hour_requests)

        return remaining_minute, remaining_hour
