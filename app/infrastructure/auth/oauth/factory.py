"""Build the OAuth provider registry from operator settings."""

from app.application.auth.registry import OAuthProviderRegistry
from app.domain.value_objects.identity_provider import IdentityProvider
from app.infrastructure.auth.oauth.github_provider import GitHubOAuthProvider
from app.infrastructure.auth.oauth.google_provider import GoogleOAuthProvider
from app.infrastructure.config.settings import Settings
from app.infrastructure.http.external_client import ExternalHttpClient


def build_oauth_registry(settings: Settings, http_client: ExternalHttpClient) -> OAuthProviderRegistry:
    providers: dict[IdentityProvider, GoogleOAuthProvider | GitHubOAuthProvider] = {}
    timeout = settings.oauth_http_timeout_seconds
    if settings.google_oauth_enabled and settings.google_client_id and settings.google_client_secret:
        providers[IdentityProvider.GOOGLE] = GoogleOAuthProvider(
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            http_client=http_client,
            timeout_seconds=timeout,
        )
    if settings.github_oauth_enabled and settings.github_client_id and settings.github_client_secret:
        providers[IdentityProvider.GITHUB] = GitHubOAuthProvider(
            client_id=settings.github_client_id,
            client_secret=settings.github_client_secret,
            http_client=http_client,
            timeout_seconds=timeout,
        )
    return OAuthProviderRegistry(providers)
