"""HTTP front door for the agent (ADR 0013/0015).

  POST /agent         blocking: returns the answer and the full trace as JSON
  POST /agent/stream  server-sent events: each trace step as it happens, then the result
  GET  /              the trace UI (static/index.html)

Every spending endpoint needs an API key (services/gateway/security.py) and is rate limited per key. A
small concurrency cap (2 runs at once, as expiring leases so a leaked slot heals itself) protects the free
tier. Errors returned to clients are generic; details go to the server log with the request id.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from services.agent.graph import AgentResult, TraceEvent, run_agent, stream_agent
from services.gateway.security import apply_daily_cap, authenticated, refund

log = structlog.get_logger()
router = APIRouter()


class Slots:
    """A small concurrency limit made of expiring leases.

    A plain semaphore leaks forever if a streaming response is cancelled before its generator starts (its
    `finally` never runs). Leases expire, so a leaked slot frees itself after `ttl` seconds.
    """

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._leases: dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self, ttl: float, now: float | None = None) -> str | None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._leases = {t: exp for t, exp in self._leases.items() if exp > now}
            if len(self._leases) >= self._capacity:
                return None
            token = uuid.uuid4().hex
            self._leases[token] = now + ttl
            return token

    def release(self, token: str) -> None:
        with self._lock:
            self._leases.pop(token, None)


_slots = Slots(2)  # free tier is 15 requests/minute; one run uses several
LEASE_GRACE_S = 60.0  # a lease outlives the run's own deadline by this much
STATIC = Path(__file__).parent / "static"


class AgentRequest(BaseModel):
    question: str = Field(min_length=8, max_length=400)


class TraceOut(BaseModel):
    kind: str
    detail: str
    seconds: float
    data: dict[str, Any]


class AgentResponse(BaseModel):
    answer: str
    refused: bool
    citations: list[dict[str, Any]]
    trace: list[TraceOut]
    steps: int
    tool_calls: int
    repairs: int


def _response(result: AgentResult) -> AgentResponse:
    return AgentResponse(
        answer=result.answer,
        refused=result.refused,
        citations=result.citations,
        trace=[TraceOut(**asdict(e)) for e in result.trace],
        steps=result.steps,
        tool_calls=result.tool_calls,
        repairs=result.repairs,
    )


def _settings_value(request: Request, name: str, default: float) -> float:
    return float(getattr(request.app.state, name, default))


def _start(request: Request, caller: str) -> tuple[str, float]:
    """Daily cap, then a concurrency slot. A request refused before any work is refunded its quota."""
    apply_daily_cap(request, caller)
    seconds = _settings_value(request, "agent_max_seconds", 120.0)
    token = _slots.acquire(ttl=seconds + LEASE_GRACE_S)
    if token is None:
        refund(request, caller)
        raise HTTPException(status_code=429, detail="agent is busy; try again in a few seconds")
    return token, seconds


def _max_steps(request: Request) -> int:
    return int(
        _settings_value(request, "agent_max_steps", 8)
    )  # server-side: clients cannot raise it


@router.get("/", include_in_schema=False)
def ui() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"cache-control": "no-store"})


@router.post("/agent", response_model=AgentResponse)
def agent(
    req: AgentRequest, request: Request, caller: str = Depends(authenticated)
) -> AgentResponse:
    llm, registry = request.app.state.agent_llm, request.app.state.registry
    token, seconds = _start(request, caller)
    try:
        result = run_agent(
            req.question, llm, registry, max_steps=_max_steps(request), max_seconds=seconds
        )
    finally:
        _slots.release(token)
    log.info("agent", refused=result.refused, steps=result.steps, tool_calls=result.tool_calls)
    return _response(result)


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.post("/agent/stream")
def agent_stream(
    req: AgentRequest, request: Request, caller: str = Depends(authenticated)
) -> StreamingResponse:
    llm, registry = request.app.state.agent_llm, request.app.state.registry  # before taking a slot
    token, seconds = _start(request, caller)
    max_steps = _max_steps(request)

    def events() -> Iterator[str]:
        try:
            for item in stream_agent(
                req.question, llm, registry, max_steps=max_steps, max_seconds=seconds
            ):
                if isinstance(item, TraceEvent):
                    yield _sse("trace", asdict(item))
                else:
                    yield _sse("result", _response(item).model_dump())
        except (
            Exception
        ) as exc:  # fail visibly, never leave the client hanging; details stay server-side
            log.error("agent_stream_failed", error=str(exc)[:300])
            yield _sse("error", {"detail": "the agent failed; see the server log for details"})
        finally:
            _slots.release(token)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )
