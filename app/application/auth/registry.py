"""OAuth provider registry. Adding a provider must not rewrite OAuthService."""

from collections.abc import Mapping

from app.application.ports.output.auth.oauth_identity_provider import OAuthIdentityProvider
from app.domain.value_objects.identity_provider import IdentityProvider


class OAuthProviderRegistry:
    """Lookup table for enabled identity adapters."""

    def __init__(self, providers: Mapping[IdentityProvider, OAuthIdentityProvider]) -> None:
        self._providers = dict(providers)

    def get(self, provider: IdentityProvider) -> OAuthIdentityProvider | None:
        return self._providers.get(provider)

    def is_registered(self, provider: IdentityProvider) -> bool:
        return provider in self._providers
