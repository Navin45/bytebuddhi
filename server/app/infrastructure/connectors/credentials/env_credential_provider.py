"""Environment and dictionary-based CredentialProvider implementation."""

import os

from app.application.ports.output.connectors.credential_provider import CredentialProvider
from app.domain.models.credential import Credential
from app.infrastructure.config.logger import get_logger

logger = get_logger(__name__)


class EnvAndDictCredentialProvider(CredentialProvider):
    """Resolves credentials with tenant/user isolation and fallback to environment variables.

    Security Rules:
    - User/project explicit credentials take priority over global fallback.
    - If user_id is provided, credentials scoped to a DIFFERENT user_id are strictly rejected.
    - Raw secrets are never written to logs or error messages.
    """

    def __init__(self, static_credentials: dict[tuple[str, str | None, str | None], Credential] | None = None) -> None:
        # Key: (provider.lower(), user_id, project_id) -> Credential
        self._store: dict[tuple[str, str | None, str | None], Credential] = dict(static_credentials or {})

    def register_credential(
        self,
        credential: Credential,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Register a scoped credential."""
        key = (credential.provider.lower().strip(), user_id, project_id)
        self._store[key] = credential

    async def set_credential(
        self,
        provider: str,
        credential: Credential,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Set a scoped credential."""
        key = (provider.lower().strip(), user_id, project_id)
        self._store[key] = credential

    async def remove_credential(
        self,
        provider: str,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> bool:
        """Remove a scoped credential if present."""
        key = (provider.lower().strip(), user_id, project_id)
        if key in self._store:
            del self._store[key]
            return True
        return False

    async def get_credential(
        self,
        provider: str,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> Credential | None:
        prov = provider.lower().strip()

        # 1. Exact match (provider, user_id, project_id)
        if (prov, user_id, project_id) in self._store:
            return self._store[(prov, user_id, project_id)]

        # 2. User-level match (provider, user_id, None)
        if user_id and (prov, user_id, None) in self._store:
            return self._store[(prov, user_id, None)]

        # 3. Project-level match (provider, None, project_id)
        if project_id and (prov, None, project_id) in self._store:
            return self._store[(prov, None, project_id)]

        # 4. Global fallback in dict (provider, None, None)
        if (prov, None, None) in self._store:
            return self._store[(prov, None, None)]

        # 5. Environment variable fallback
        env_secret = None
        if prov == "github":
            env_secret = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT")
        elif prov == "slack":
            env_secret = os.getenv("SLACK_BOT_TOKEN")

        if env_secret:
            return Credential(
                provider=prov,
                credential_id=f"env_{prov}",
                secret=env_secret,
                metadata={"source": "environment"},
            )

        return None
