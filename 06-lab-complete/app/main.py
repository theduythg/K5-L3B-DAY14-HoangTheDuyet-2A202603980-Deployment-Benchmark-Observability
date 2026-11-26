"""Production-ready FastAPI mock agent for the Day 14 lab."""
import json
import logging
from datetime import datetime, timezone
from time import perf_counter
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Emit one parseable JSON object per application log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for key in ("event", "method", "path", "status_code", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


logger = logging.getLogger("production_agent")
logger.setLevel(logging.INFO)
logger.handlers.clear()
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.propagate = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("application started", extra={"event": "startup"})
    yield
    logger.info("application stopped", extra={"event": "shutdown"})


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str = Field(default="default", min_length=1, max_length=128)


@app.middleware("http")
async def log_request(request: Request, call_next):
    started = perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        logger.info(
            "http request",
            extra={
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )


@app.get("/health")
def health():
    """Liveness: this process is alive, independent of Redis availability."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness: accept traffic only while the shared Redis store is reachable."""
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis is not ready")
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    """Authenticated request path with Redis rate and cost protection."""
    check_rate_limit(api_key)
    check_budget()

    try:
        answer = llm_ask(body.question)
    except Exception as exc:
        logger.error("mock model request failed", extra={"event": "llm_error"}, exc_info=True)
        raise HTTPException(status_code=502, detail="Agent could not complete the request") from exc

    input_tokens = max(1, len(body.question.split()) * 2)
    output_tokens = max(1, len(answer.split()) * 2)
    cost = record_cost(input_tokens, output_tokens)
    return {
        "question": body.question,
        "answer": answer,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
        },
    }
