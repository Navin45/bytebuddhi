"""Domain model for external connector credentials."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CredentialType(StrEnum):
    """Supported connector credential types."""

    BEARER_TOKEN = "bearer_token"
    API_KEY = "api_key"
    BASIC_AUTH = "basic_auth"
    OAUTH2 = "oauth2"


@dataclass(frozen=True)
class Credential:
    """Represents an authentication credential for an external provider.

    Security Invariant:
        The raw secret is ephemeral in-memory only and must never be serialized
        into model context, memory, logs, or telemetry.
    """

    provider: str
    credential_id: str = ""
    secret: str = ""
    name: str = ""
    secret_value: str = ""
    credential_type: CredentialType = CredentialType.BEARER_TOKEN
    metadata: dict[str, Any] = field(default_factory=dict)
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.credential_id and self.name:
            object.__setattr__(self, "credential_id", self.name)
        elif not self.name and self.credential_id:
            object.__setattr__(self, "name", self.credential_id)

        if not self.secret and self.secret_value:
            object.__setattr__(self, "secret", self.secret_value)
        elif not self.secret_value and self.secret:
            object.__setattr__(self, "secret_value", self.secret)

    @property
    def is_expired(self) -> bool:
        """Check if credential has expired."""
        if self.expires_at is None:
            return False
        now = datetime.now(UTC)
        target = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=UTC)
        return now > target

    def masked_secret(self) -> str:
        """Return safe masked representation for logging/diagnostics without leaking secrets."""
        val = self.secret or self.secret_value
        if not val:
            return ""
        if len(val) <= 8:
            return "******"
        prefix = val[:4]
        suffix = val[-4:]
        return f"{prefix}...{suffix}"

    def to_safe_dict(self) -> dict[str, Any]:
        """Serialize metadata and identity without raw secret."""
        return {
            "name": self.name,
            "provider": self.provider,
            "credential_id": self.credential_id,
            "credential_type": self.credential_type.value,
            "secret": self.masked_secret(),
            "metadata": self.metadata,
            "is_expired": self.is_expired,
        }
