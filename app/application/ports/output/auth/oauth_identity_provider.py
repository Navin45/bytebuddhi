"""OAuth identity provider port. SDKs stay in infrastructure adapters."""

from typing import Protocol

from app.application.auth.identity_data import ExternalIdentityData
from app.domain.value_objects.identity_provider import IdentityProvider


class OAuthIdentityProvider(Protocol):
    """Authorization-code identity provider used only for login/linking."""

    @property
    def provider(self) -> IdentityProvider:
        """Canonical provider value."""

    def build_authorization_url(
        self,
        *,
        state: str,
        code_challenge: str,
        redirect_uri: str,
    ) -> str:
        """Build the provider authorization URL. Must include the given state."""

    async def exchange_code(
        self,
        *,
        code: str,
        code_verifier: str,
        redirect_uri: str,
    ) -> ExternalIdentityData:
        """Exchange a one-time authorization code and return a normalized identity.

        Must not persist provider access or refresh tokens.
        """
