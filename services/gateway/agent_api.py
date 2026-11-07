"""HTTP front door for the agent (ADR 0013/0015).

  POST /agent         blocking: returns the answer and the full trace as JSON
  POST /agent/stream  server-sent events: each trace step as it happens, then the result
  GET  /              the trace UI (static/index.html)

No authentication or rate limiting per user yet (Phase 4): this spends the Gemini quota, so it is
for local/dev use. A small concurrency cap (2 runs at once) protects the free tier meanwhile.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from services.agent.graph import AgentResult, TraceEvent, run_agent, stream_agent

log = structlog.get_logger()
router = APIRouter()
_slots = threading.BoundedSemaphore(2)  # free tier is 15 requests/minute; one run uses several
STATIC = Path(__file__).parent / "static"


class AgentRequest(BaseModel):
    question: str = Field(min_length=8, max_length=400)
    max_steps: int = Field(default=8, ge=2, le=12)


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


def _acquire() -> None:
    if not _slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="agent is busy; try again in a few seconds")


@router.get("/", include_in_schema=False)
def ui() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"cache-control": "no-store"})


@router.post("/agent", response_model=AgentResponse)
def agent(req: AgentRequest, request: Request) -> AgentResponse:
    _acquire()
    try:
        result = run_agent(
            req.question,
            request.app.state.agent_llm,
            request.app.state.registry,
            max_steps=req.max_steps,
        )
    finally:
        _slots.release()
    log.info("agent", refused=result.refused, steps=result.steps, tool_calls=result.tool_calls)
    return _response(result)


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.post("/agent/stream")
def agent_stream(req: AgentRequest, request: Request) -> StreamingResponse:
    _acquire()
    llm, registry = request.app.state.agent_llm, request.app.state.registry

    def events() -> Iterator[str]:
        try:
            for item in stream_agent(req.question, llm, registry, max_steps=req.max_steps):
                if isinstance(item, TraceEvent):
                    yield _sse("trace", asdict(item))
                else:
                    yield _sse("result", _response(item).model_dump())
        except Exception as exc:  # fail visibly, never leave the client hanging
            log.error("agent_stream_failed", error=str(exc)[:200])
            yield _sse("error", {"detail": f"agent failed: {str(exc)[:150]}"})
        finally:
            _slots.release()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )
