"""Rate limiting middleware for FastAPI.

This module provides rate limiting functionality to protect the API
from abuse and ensure fair usage across all users.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Tuple

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using in-memory storage.
    
    This middleware tracks request counts per IP address and enforces
    rate limits. For production, consider using Redis for distributed
    rate limiting.
    
    Attributes:
        rate_limit_per_minute: Maximum requests per minute
        rate_limit_per_hour: Maximum requests per hour
        request_counts: In-memory storage of request counts
    """

    def __init__(self, app):
        """Initialize rate limiter.
        
        Args:
            app: FastAPI application instance
        """
        super().__init__(app)
        self.rate_limit_per_minute = settings.rate_limit_per_minute
        self.rate_limit_per_hour = settings.rate_limit_per_hour
        
        # Storage: {ip: {minute: [(timestamp, count)], hour: [(timestamp, count)]}}
        self.request_counts: Dict[str, Dict[str, list]] = defaultdict(
            lambda: {"minute": [], "hour": []}
        )

    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting.
        
        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain
            
        Returns:
            Response from next handler
            
        Raises:
            HTTPException: If rate limit is exceeded
        """
        # Skip rate limiting for health check and docs
        if request.url.path in ["/", "/health", "/api/v1/health", "/api/docs", "/api/redoc"]:
            return await call_next(request)
        
        # Get client IP
        client_ip = self._get_client_ip(request)
        
        # Check rate limits
        try:
            self._check_rate_limit(client_ip)
        except HTTPException:
            logger.warning(
                "Rate limit exceeded",
                ip=client_ip,
                path=request.url.path,
            )
            raise
        
        # Record request
        self._record_request(client_ip)
        
        # Clean old entries periodically
        self._cleanup_old_entries(client_ip)
        
        # Process request
        response = await call_next(request)
        
        # Add rate limit headers
        remaining_minute, remaining_hour = self._get_remaining_requests(client_ip)
        response.headers["X-RateLimit-Limit-Minute"] = str(self.rate_limit_per_minute)
        response.headers["X-RateLimit-Limit-Hour"] = str(self.rate_limit_per_hour)
        response.headers["X-RateLimit-Remaining-Minute"] = str(remaining_minute)
        response.headers["X-RateLimit-Remaining-Hour"] = str(remaining_hour)
        
        return response

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request.
        
        Checks X-Forwarded-For header first (for proxies), then falls back
        to direct client IP.
        
        Args:
            request: HTTP request
            
        Returns:
            str: Client IP address
        """
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _check_rate_limit(self, client_ip: str) -> None:
        """Check if client has exceeded rate limits.
        
        Args:
            client_ip: Client IP address
            
        Raises:
            HTTPException: If rate limit is exceeded
        """
        now = datetime.utcnow()
        counts = self.request_counts[client_ip]
        
        # Check minute limit
        minute_ago = now - timedelta(minutes=1)
        minute_requests = sum(
            1 for timestamp in counts["minute"]
            if timestamp > minute_ago
        )
        
        if minute_requests >= self.rate_limit_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {self.rate_limit_per_minute} requests per minute",
                headers={"Retry-After": "60"},
            )
        
        # Check hour limit
        hour_ago = now - timedelta(hours=1)
        hour_requests = sum(
            1 for timestamp in counts["hour"]
            if timestamp > hour_ago
        )
        
        if hour_requests >= self.rate_limit_per_hour:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {self.rate_limit_per_hour} requests per hour",
                headers={"Retry-After": "3600"},
            )

    def _record_request(self, client_ip: str) -> None:
        """Record a request for rate limiting.
        
        Args:
            client_ip: Client IP address
        """
        now = datetime.utcnow()
        counts = self.request_counts[client_ip]
        counts["minute"].append(now)
        counts["hour"].append(now)

    def _cleanup_old_entries(self, client_ip: str) -> None:
        """Remove old entries to prevent memory growth.
        
        Args:
            client_ip: Client IP address
        """
        now = datetime.utcnow()
        counts = self.request_counts[client_ip]
        
        # Keep only last minute for minute tracking
        minute_ago = now - timedelta(minutes=1)
        counts["minute"] = [
            timestamp for timestamp in counts["minute"]
            if timestamp > minute_ago
        ]
        
        # Keep only last hour for hour tracking
        hour_ago = now - timedelta(hours=1)
        counts["hour"] = [
            timestamp for timestamp in counts["hour"]
            if timestamp > hour_ago
        ]
        
        # Remove IP if no recent requests
        if not counts["minute"] and not counts["hour"]:
            del self.request_counts[client_ip]

    def _get_remaining_requests(self, client_ip: str) -> Tuple[int, int]:
        """Get remaining requests for client.
        
        Args:
            client_ip: Client IP address
            
        Returns:
            Tuple[int, int]: (remaining_minute, remaining_hour)
        """
        now = datetime.utcnow()
        counts = self.request_counts[client_ip]
        
        minute_ago = now - timedelta(minutes=1)
        minute_requests = sum(
            1 for timestamp in counts["minute"]
            if timestamp > minute_ago
        )
        
        hour_ago = now - timedelta(hours=1)
        hour_requests = sum(
            1 for timestamp in counts["hour"]
            if timestamp > hour_ago
        )
        
        remaining_minute = max(0, self.rate_limit_per_minute - minute_requests)
        remaining_hour = max(0, self.rate_limit_per_hour - hour_requests)
        
        return remaining_minute, remaining_hour
