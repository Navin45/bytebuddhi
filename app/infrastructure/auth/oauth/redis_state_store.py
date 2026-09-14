"""Redis-backed OAuth state and exchange tickets."""

from __future__ import annotations

import json
from typing import Any

from app.application.ports.output.auth.oauth_state_store import OAuthStateRecord, OAuthStateStore
from app.domain.value_objects.identity_provider import IdentityProvider, OAuthClientKind, OAuthFlow

STATE_PREFIX = "bytebuddhi:oauth:state:"
EXCHANGE_PREFIX = "bytebuddhi:oauth:exchange:"


class RedisOAuthStateStore(OAuthStateStore):
    """Single-use OAuth tickets using Redis SET NX + GETDEL."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def put_state(self, state: str, record: OAuthStateRecord, ttl_seconds: int) -> None:
        payload = json.dumps(
            {
                "provider": record.provider.value,
                "flow": record.flow.value,
                "client": record.client.value,
                "code_verifier": record.code_verifier,
                "user_id": record.user_id,
            }
        )
        stored = await self._client.set(f"{STATE_PREFIX}{state}", payload, ex=ttl_seconds, nx=True)
        if not stored:
            raise RuntimeError("OAuth state token could not be stored")

    async def consume_state(self, state: str) -> OAuthStateRecord | None:
        raw = await self._client.getdel(f"{STATE_PREFIX}{state}")
        if raw is None:
            return None
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        data = json.loads(text)
        return OAuthStateRecord(
            provider=IdentityProvider(data["provider"]),
            flow=OAuthFlow(data["flow"]),
            client=OAuthClientKind(data["client"]),
            code_verifier=data["code_verifier"],
            user_id=data.get("user_id"),
        )

    async def put_exchange(self, code: str, user_id: str, ttl_seconds: int) -> None:
        stored = await self._client.set(f"{EXCHANGE_PREFIX}{code}", user_id.encode(), ex=ttl_seconds, nx=True)
        if not stored:
            raise RuntimeError("OAuth exchange code could not be stored")

    async def consume_exchange(self, code: str) -> str | None:
        raw = await self._client.getdel(f"{EXCHANGE_PREFIX}{code}")
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)
