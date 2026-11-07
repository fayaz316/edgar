"""HTTP contract for the agent endpoints, with a scripted model: no network, no database."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.agent.llm import ModelTurn
from services.agent.tests.test_agent import FakeRetriever, ScriptedLLM, _search
from services.gateway import agent_api
from services.gateway.main import app
from services.tools.filings import ToolContext, build_registry
from services.tools.tests.test_registry import _Pool

client = TestClient(app)
QUESTION = "How do export controls affect NVIDIA demand?"


@pytest.fixture
def wire() -> Iterator[Any]:
    def _wire(turns: list[ModelTurn]) -> None:
        ctx = ToolContext(retriever=FakeRetriever(), pool=_Pool([]))  # type: ignore[arg-type]
        app.state.registry = build_registry(ctx)
        app.state.agent_llm = ScriptedLLM(turns)

    yield _wire
    for name in ("registry", "agent_llm"):
        if hasattr(app.state, name):
            delattr(app.state, name)


def _sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_agent_returns_answer_citations_and_trace(wire: Any) -> None:
    wire([_search(), ModelTurn(text="Export controls hurt demand [1].")])
    r = client.post("/agent", json={"question": QUESTION})
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False and body["answer"].endswith("[1].")
    assert [t["kind"] for t in body["trace"]] == ["model", "tool", "model", "verify"]
    assert body["citations"][0]["ticker"] == "NVDA" and "text" in body["citations"][0]
    assert body["steps"] == 2 and body["tool_calls"] == 1


def test_agent_refusal_is_a_normal_200(wire: Any) -> None:
    wire([ModelTurn(text="INSUFFICIENT_CONTEXT. Not in the filings.")])
    r = client.post("/agent", json={"question": "What was Tesla revenue in 2025?"})
    assert r.status_code == 200 and r.json()["refused"] is True


def test_stream_sends_trace_events_in_order_then_the_result(wire: Any) -> None:
    wire([_search(), ModelTurn(text="Export controls hurt demand [1].")])
    r = client.post("/agent/stream", json={"question": QUESTION})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = _sse(r.text)
    assert [name for name, _ in events] == ["trace", "trace", "trace", "trace", "result"]
    assert [d["kind"] for n, d in events if n == "trace"] == ["model", "tool", "model", "verify"]
    assert events[-1][1]["refused"] is False


def test_stream_turns_an_unexpected_failure_into_an_error_event(
    wire: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire([])

    def boom(*a: Any, **k: Any) -> Iterator[Any]:
        raise RuntimeError("database exploded")
        yield  # pragma: no cover

    monkeypatch.setattr(agent_api, "stream_agent", boom)
    r = client.post("/agent/stream", json={"question": QUESTION})
    [(name, data)] = _sse(r.text)
    assert name == "error" and "database exploded" in data["detail"]


def test_questions_that_are_too_short_or_too_long_are_422(wire: Any) -> None:
    wire([])
    assert client.post("/agent", json={"question": "hi"}).status_code == 422
    assert client.post("/agent", json={"question": "x" * 401}).status_code == 422


def test_busy_agent_returns_429_and_releases_slots_afterwards(wire: Any) -> None:
    wire([ModelTurn(text="INSUFFICIENT_CONTEXT. none.")])
    held = [agent_api._slots.acquire(blocking=False) for _ in range(2)]
    try:
        assert all(held)
        assert client.post("/agent", json={"question": QUESTION}).status_code == 429
    finally:
        for _ in range(2):
            agent_api._slots.release()
    assert client.post("/agent", json={"question": QUESTION}).status_code == 200  # slot freed


def test_ui_page_is_served_and_uses_no_innerhtml() -> None:
    r = client.get("/")
    assert r.status_code == 200 and "Edgar Analyst" in r.text
    assert "innerHTML" not in r.text.replace(
        "never innerHTML", ""
    )  # untrusted text goes via textContent
