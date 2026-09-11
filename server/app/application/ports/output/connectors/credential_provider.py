"""Output port protocol for resolving external connector credentials."""

from typing import Protocol, runtime_checkable

from app.domain.models.credential import Credential


@runtime_checkable
class CredentialProvider(Protocol):
    """Abstract port for resolving provider authentication credentials."""

    async def get_credential(
        self,
        provider: str,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> Credential | None:
        """Resolve credential for the specified provider and caller scope.

        Args:
            provider: Canonical provider identifier (e.g., 'github', 'slack').
            user_id: Authenticated caller user ID from execution context.
            project_id: Active project ID from execution context.

        Returns:
            Optional[Credential]: Resolved credential or None if unconfigured.
        """
        ...
