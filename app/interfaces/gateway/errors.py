"""Typed gateway failures. Messages are safe to show to users."""

from __future__ import annotations

import re

_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]+")
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
_AUTH_HEADER_RE = re.compile(r"(?i)authorization\s*[:=]\s*\S+")


def redact_secrets(text: str, *secrets: str) -> str:
    """Remove bearer tokens, JWTs, and known secret values from text."""
    redacted = _BEARER_RE.sub("Bearer [REDACTED]", text)
    redacted = _JWT_RE.sub("[REDACTED]", redacted)
    redacted = _AUTH_HEADER_RE.sub("Authorization: [REDACTED]", redacted)
    for secret in secrets:
        if secret and len(secret) >= 8 and secret in redacted:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


class GatewayError(Exception):
    """Base client/manager error. ``message`` is user-facing and redacted."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class GatewayConfigError(GatewayError):
    """Invalid gateway URL, host, or port."""

    def __init__(self, message: str, *, usage: bool = False) -> None:
        super().__init__(message)
        self.usage = usage


class AuthenticationRequired(GatewayError):
    """HTTP 401. The access token is missing, invalid, or expired."""


class AuthorizationDenied(GatewayError):
    """HTTP 403. The authenticated user may not access the resource."""


class ResourceNotFound(GatewayError):
    """HTTP 404."""


class Conflict(GatewayError):
    """HTTP 409."""


class InvalidRequest(GatewayError):
    """HTTP 400 or 422."""


class RateLimited(GatewayError):
    """HTTP 429."""


class GatewayServerError(GatewayError):
    """HTTP 5xx from the gateway."""


class GatewayTimeout(GatewayError):
    """The gateway did not respond within the finite client timeout."""


class GatewayUnavailable(GatewayError):
    """The gateway could not be reached. Embedded mode is not a fallback."""


class MalformedResponse(GatewayError):
    """The gateway returned a body that does not match the API contract."""


class GatewayPortConflict(GatewayError):
    """The configured port is taken by a process that is not this gateway."""


class GatewayStartTimeout(GatewayError):
    """The gateway process started but readiness did not succeed in time."""


class GatewayStartFailed(GatewayError):
    """The gateway process exited or could not be launched."""


class ProtocolIncompatible(GatewayError):
    """Client protocol version is incompatible with the gateway protocol version."""
