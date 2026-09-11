"""Domain and infrastructure exceptions for external connectors."""

from typing import Any


class ConnectorError(Exception):
    """Base exception for all external connector failures."""

    def __init__(
        self,
        message: str,
        provider: str = "",
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.details = details or {}


class ConnectorAuthenticationError(ConnectorError):
    """Authentication failed with the external provider (e.g. invalid or missing token)."""


class ConnectorAuthorizationError(ConnectorError):
    """Caller is unauthorized to access or mutate the external resource."""


class ConnectorRateLimitError(ConnectorError):
    """External provider rate limit exceeded."""

    def __init__(
        self,
        message: str,
        provider: str = "",
        retry_after: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, provider=provider, status_code=429, details=details)
        self.retry_after = retry_after


class ConnectorNotFoundError(ConnectorError):
    """External resource was not found (HTTP 404)."""


class ConnectorTimeoutError(ConnectorError):
    """External request timed out."""


class ConnectorServiceError(ConnectorError):
    """External provider service error (HTTP 5xx)."""
