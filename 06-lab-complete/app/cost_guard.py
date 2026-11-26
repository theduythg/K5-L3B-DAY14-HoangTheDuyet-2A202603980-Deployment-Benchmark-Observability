"""Daily LLM cost budget stored centrally in Redis."""
from datetime import datetime, timedelta, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r


PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _daily_key() -> str:
    day = datetime.now(timezone.utc).date().isoformat()
    return f"agent:cost:{day}"


def check_budget() -> None:
    """Reject requests once today's accumulated cost reaches the configured cap."""
    try:
        spent = float(r.get(_daily_key()) or 0.0)
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Cost guard unavailable") from exc
    if spent >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail="Daily budget exceeded")


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate request cost from token counts, then atomically add it to Redis."""
    input_tokens = max(0, int(input_tokens))
    output_tokens = max(0, int(output_tokens))
    cost = (input_tokens / 1000 * PRICE_INPUT_PER_1K
            + output_tokens / 1000 * PRICE_OUTPUT_PER_1K)
    key = _daily_key()
    try:
        r.incrbyfloat(key, cost)
        r.expire(key, int(timedelta(days=2).total_seconds()))
    except redis.RedisError as exc:
        raise HTTPException(status_code=503, detail="Cost recording unavailable") from exc
    return cost
