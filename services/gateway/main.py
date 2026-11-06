"""Edgar Analyst gateway — Phase 0 skeleton.

Expert bar held from commit one: typed configs, structured JSON logs with
request correlation, liveness/readiness split, and zero-downtime deploy checks.
RAG/agent handlers arrive in later phases; the observability spine lands now.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime config. Env prefix EA_; secrets never live in code or tfvars."""

    model_config = SettingsConfigDict(env_prefix="EA_", env_file=".env")

    environment: str = "dev"  # dev | prod — drives log verbosity and feature gates
    log_level: str = "INFO"


settings = Settings()
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(structlog, settings.log_level.upper(), 20)
    ),
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ],
)
log = structlog.get_logger()


app = FastAPI(title="Edgar Analyst Gateway", version="0.1.0")


@app.middleware("http")
async def observability(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach request id + emit one structured access line per request."""
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    structlog.contextvars.bind_contextvars(request_id=request_id)
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["x-request-id"] = request_id
    log.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round(elapsed_ms, 2),
    )
    return response


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: process is up. Never checks dependencies (that's readiness)."""
    return {"status": "ok", "env": settings.environment}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    """Readiness: safe to receive traffic. Dependency checks grow here per phase."""
    return {"status": "ready"}


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": "edgar-analyst-gateway",
        "phase": "0 — guardrails",
        "docs": "/docs",
    }
