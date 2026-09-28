"""Atomic global admission. A dead worker's slot expires with its TTL."""

from __future__ import annotations

from typing import Any

from app.application.runs.admission import AdmissionDenied, AdmissionUnavailable

_SET = "bytebuddhi:admission"
_SLOT = "bytebuddhi:admission:slot:"

_ACQUIRE = """
local setkey = KEYS[1]
local slot = KEYS[2]
local max = tonumber(ARGV[1])
local run_id = ARGV[2]
local worker = ARGV[3]
local ttl = tonumber(ARGV[4])
local prefix = ARGV[5]
local members = redis.call('SMEMBERS', setkey)
for _, id in ipairs(members) do
  if redis.call('EXISTS', prefix .. id) == 0 then
    redis.call('SREM', setkey, id)
  end
end
local owner = redis.call('GET', slot)
if owner == worker then
  redis.call('EXPIRE', slot, ttl)
  return 1
end
if owner then
  return 0
end
if redis.call('SCARD', setkey) >= max then
  return 0
end
redis.call('SADD', setkey, run_id)
redis.call('SET', slot, worker, 'EX', ttl)
return 1
"""

_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('DEL', KEYS[1])
  redis.call('SREM', KEYS[2], ARGV[2])
  return 1
end
return 0
"""


class RedisRunAdmission:
    """Shared active-run limit. HTTP workers do not hold these slots."""

    mode = "redis"

    def __init__(self, client: Any, max_active: int) -> None:
        if max_active < 1:
            raise ValueError("max_active must be >= 1")
        self._client = client
        self.max_active = max_active

    async def acquire(self, run_id: str, worker_id: str, ttl_seconds: float) -> None:
        try:
            allowed = await self._client.eval(
                _ACQUIRE,
                2,
                _SET,
                _SLOT + run_id,
                str(self.max_active),
                run_id,
                worker_id,
                str(max(1, int(ttl_seconds))),
                _SLOT,
            )
        except Exception as exc:
            raise AdmissionUnavailable() from exc
        if not int(allowed):
            raise AdmissionDenied()

    async def release(self, run_id: str, worker_id: str) -> None:
        try:
            await self._client.eval(_RELEASE, 2, _SLOT + run_id, _SET, worker_id, run_id)
        except Exception as exc:
            raise AdmissionUnavailable() from exc

    async def renew(self, run_id: str, worker_id: str, ttl_seconds: float) -> bool:
        try:
            await self.acquire(run_id, worker_id, ttl_seconds)
        except AdmissionDenied:
            return False
        return True
