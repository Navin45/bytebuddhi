"""OAuth state and one-time exchange ticket store."""

from dataclasses import dataclass
from typing import Protocol

from app.domain.value_objects.identity_provider import IdentityProvider, OAuthClientKind, OAuthFlow


@dataclass(frozen=True)
class OAuthStateRecord:
    """Single-use login or link attempt. Bound to one provider and client."""

    provider: IdentityProvider
    flow: OAuthFlow
    client: OAuthClientKind
    code_verifier: str
    user_id: str | None = None


class OAuthStateStore(Protocol):
    """Cryptographically random, short-lived, single-use OAuth tickets."""

    async def put_state(self, state: str, record: OAuthStateRecord, ttl_seconds: int) -> None:
        """Store a new state token. Must not overwrite an existing token."""

    async def consume_state(self, state: str) -> OAuthStateRecord | None:
        """Atomically read and delete a state token. None if missing or expired."""

    async def put_exchange(self, code: str, user_id: str, ttl_seconds: int) -> None:
        """Store a one-time ByteBuddhi token-exchange code."""

    async def consume_exchange(self, code: str) -> str | None:
        """Atomically read and delete an exchange code. Returns user_id or None."""
