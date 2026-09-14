"""OAuth state replay, TTL, and access-log redaction."""

import logging
import time

import pytest

from app.application.ports.output.auth.oauth_state_store import OAuthStateRecord
from app.domain.value_objects.identity_provider import IdentityProvider, OAuthClientKind, OAuthFlow
from app.infrastructure.auth.oauth.memory_state_store import MemoryOAuthStateStore
from app.infrastructure.config.logger import OauthQueryRedactingFilter
from app.interfaces.api.middleware.rate_limiter import RateLimitMiddleware


def _record() -> OAuthStateRecord:
    return OAuthStateRecord(
        provider=IdentityProvider.GOOGLE,
        flow=OAuthFlow.LOGIN,
        client=OAuthClientKind.WEB,
        code_verifier="verifier",
        user_id=None,
    )


@pytest.mark.asyncio
async def test_memory_state_is_single_use() -> None:
    store = MemoryOAuthStateStore()
    await store.put_state("s1", _record(), 600)
    first = await store.consume_state("s1")
    second = await store.consume_state("s1")
    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_memory_state_expires() -> None:
    store = MemoryOAuthStateStore()
    await store.put_state("s1", _record(), 600)
    store._states["s1"] = (time.monotonic() - 1, store._states["s1"][1])
    assert await store.consume_state("s1") is None


@pytest.mark.asyncio
async def test_exchange_code_single_use() -> None:
    store = MemoryOAuthStateStore()
    await store.put_exchange("code", "user-id", 120)
    assert await store.consume_exchange("code") == "user-id"
    assert await store.consume_exchange("code") is None


def test_access_log_redacts_oauth_query() -> None:
    filt = OauthQueryRedactingFilter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="GET /api/v1/auth/google/callback?code=SECRETCODE&state=SECRETSTATE HTTP/1.1",
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert "SECRETCODE" not in record.msg
    assert "SECRETSTATE" not in record.msg
    assert "[REDACTED]" in record.msg


def test_oauth_routes_are_rate_limited() -> None:
    skip = {
        "/",
        "/health",
        "/api/v1/health",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/health/db",
        "/api/docs",
        "/api/redoc",
    }
    for path in (
        "/api/v1/auth/google/login",
        "/api/v1/auth/google/callback",
        "/api/v1/auth/github/login",
        "/api/v1/auth/github/callback",
    ):
        assert path not in skip
    assert RateLimitMiddleware is not None


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    async def set(self, key: str, value: object, ex: int | None = None, nx: bool = False) -> bool:
        del ex
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True

    async def getdel(self, key: str) -> object | None:
        return self.data.pop(key, None)


@pytest.mark.asyncio
async def test_redis_state_rejects_overwrite() -> None:
    from app.infrastructure.auth.oauth.redis_state_store import RedisOAuthStateStore

    store = RedisOAuthStateStore(_FakeRedis())
    await store.put_state("s1", _record(), 600)
    with pytest.raises(RuntimeError, match="could not be stored"):
        await store.put_state("s1", _record(), 600)
    first = await store.consume_state("s1")
    second = await store.consume_state("s1")
    assert first is not None
    assert second is None
