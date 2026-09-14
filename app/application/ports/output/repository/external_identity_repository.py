"""Repository for ExternalIdentity records."""

from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.models.external_identity import ExternalIdentity
from app.domain.models.user import User
from app.domain.value_objects.identity_provider import IdentityProvider


class ExternalIdentityRepository(ABC):
    """Persistence for linked external identities."""

    @abstractmethod
    async def get_by_provider_subject(
        self,
        provider: IdentityProvider,
        provider_subject: str,
    ) -> ExternalIdentity | None:
        """Look up a unique (provider, provider_subject) link."""

    @abstractmethod
    async def list_by_user_id(self, user_id: UUID) -> list[ExternalIdentity]:
        """List identities linked to a user."""

    @abstractmethod
    async def create_with_user(self, user: User, identity: ExternalIdentity) -> ExternalIdentity:
        """Create User and ExternalIdentity in one transaction. No network I/O."""

    @abstractmethod
    async def create(self, identity: ExternalIdentity) -> ExternalIdentity:
        """Link an identity to an existing user."""

    @abstractmethod
    async def delete(self, user_id: UUID, provider: IdentityProvider) -> bool:
        """Remove a provider link for a user. Returns True if a row was deleted."""
