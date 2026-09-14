"""Runtime OAuth configuration viewed by the application layer."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OAuthRuntimeConfig:
    """Operator OAuth settings without secrets."""

    google_enabled: bool
    github_enabled: bool
    google_redirect_uri: str
    github_redirect_uri: str
    state_ttl_seconds: int
    exchange_ttl_seconds: int
    post_login_redirect: str | None
    vscode_redirect: str | None
    cli_redirect: str | None
