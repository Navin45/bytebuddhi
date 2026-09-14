"""External identity linked to a ByteBuddhi user.

The canonical runtime identity remains User.id. Provider subject is never
used as an internal user id.
"""

from datetime import datetime
from uuid import UUID, uuid4

from app.domain.value_objects.identity_provider import IdentityProvider


class ExternalIdentity:
    """Link between a User and a stable provider subject."""

    def __init__(
        self,
        id: UUID,
        user_id: UUID,
        provider: IdentityProvider,
        provider_subject: str,
        created_at: datetime,
        updated_at: datetime,
        email_snapshot: str | None = None,
        display_name_snapshot: str | None = None,
        avatar_url_snapshot: str | None = None,
    ) -> None:
        self.id = id
        self.user_id = user_id
        self.provider = provider
        self.provider_subject = provider_subject
        self.email_snapshot = email_snapshot
        self.display_name_snapshot = display_name_snapshot
        self.avatar_url_snapshot = avatar_url_snapshot
        self.created_at = created_at
        self.updated_at = updated_at

    @staticmethod
    def create(
        user_id: UUID,
        provider: IdentityProvider,
        provider_subject: str,
        email_snapshot: str | None = None,
        display_name_snapshot: str | None = None,
        avatar_url_snapshot: str | None = None,
    ) -> "ExternalIdentity":
        now = datetime.utcnow()
        return ExternalIdentity(
            id=uuid4(),
            user_id=user_id,
            provider=provider,
            provider_subject=provider_subject,
            email_snapshot=email_snapshot,
            display_name_snapshot=display_name_snapshot,
            avatar_url_snapshot=avatar_url_snapshot,
            created_at=now,
            updated_at=now,
        )
