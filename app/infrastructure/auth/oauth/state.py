"""OAuth state store process holder."""

from app.application.ports.output.auth.oauth_state_store import OAuthStateStore
from app.infrastructure.auth.oauth.memory_state_store import MemoryOAuthStateStore

_store: OAuthStateStore = MemoryOAuthStateStore()


def get_oauth_state_store() -> OAuthStateStore:
    return _store


def attach_oauth_state_store(store: OAuthStateStore) -> None:
    global _store
    _store = store
