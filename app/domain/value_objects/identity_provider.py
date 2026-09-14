"""Canonical external identity providers for authentication."""

from enum import StrEnum


class IdentityProvider(StrEnum):
    """Login identity providers. Not GitHub/Google resource connectors."""

    GOOGLE = "google"
    GITHUB = "github"


class OAuthClientKind(StrEnum):
    """Post-login client that may receive a one-time exchange code."""

    WEB = "web"
    VSCODE = "vscode"
    CLI = "cli"


class OAuthFlow(StrEnum):
    """OAuth state is bound to exactly one of these flows."""

    LOGIN = "login"
    LINK = "link"


class AuthFailureCategory(StrEnum):
    """Normalized authentication failure categories. Safe to log and return."""

    USER_DENIED = "user_denied"
    STATE_INVALID = "state_invalid"
    STATE_EXPIRED = "state_expired"
    CODE_EXCHANGE_FAILED = "code_exchange_failed"
    IDENTITY_VERIFICATION_FAILED = "identity_verification_failed"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    CONFIGURATION_ERROR = "configuration_error"
    AUTHENTICATION_FAILED = "authentication_failed"
    LAST_CREDENTIAL = "last_credential"
    IDENTITY_ALREADY_LINKED = "identity_already_linked"
    PROVIDER_DISABLED = "provider_disabled"
    INVALID_REQUEST = "invalid_request"
    UNAUTHORIZED = "unauthorized"
