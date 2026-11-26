"""Atomic, Redis backed sliding-window rate limiter."""
import hashlib
import math
import secrets
import time

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r


WINDOW_SECONDS = 60

# Redis evaluates this script atomically across all uvicorn workers/instances.
_SLIDING_WINDOW = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local cutoff_ms = tonumber(ARGV[2])
local window_ms = tonumber(ARGV[3])
local limit = tonumber(ARGV[4])
local member = ARGV[5]
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff_ms)
local count = redis.call('ZCARD', key)
if count >= limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry_ms = window_ms
  if oldest[2] then retry_ms = math.max(1, tonumber(oldest[2]) + window_ms - now_ms) end
  return {0, retry_ms}
end
redis.call('ZADD', key, now_ms, member)
redis.call('EXPIRE', key, 120)
return {1, 0}
"""


def check_rate_limit(key: str) -> None:
    """Allow at most the configured requests in the trailing 60 seconds."""
    now_ms = int(time.time() * 1000)
    window_ms = WINDOW_SECONDS * 1000
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    redis_key = f"agent:rate:{digest}"
    member = f"{now_ms}:{secrets.token_hex(8)}"

    try:
        allowed, retry_ms = r.eval(
            _SLIDING_WINDOW,
            1,
            redis_key,
            now_ms,
            now_ms - window_ms,
            window_ms,
            max(1, settings.rate_limit_per_minute),
            member,
        )
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable") from exc

    if int(allowed) == 0:
        retry_after = max(1, math.ceil(int(retry_ms) / 1000))
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
