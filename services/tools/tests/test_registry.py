from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from services.gateway.retrieval import RetrievedChunk
from services.tools.filings import ToolContext, build_registry
from services.tools.registry import Tool, ToolError, ToolRegistry


class _Echo(BaseModel):
    text: str


def _echo(ctx: Any, p: BaseModel) -> dict[str, Any]:
    assert isinstance(p, _Echo)
    return {"echo": p.text, "ctx": ctx}


def test_call_validates_then_runs_the_handler() -> None:
    reg = ToolRegistry(context="CTX")
    reg.register(Tool("echo", "echoes", _Echo, _echo))
    assert reg.call("echo", {"text": "hi"}) == {"echo": "hi", "ctx": "CTX"}


def test_invalid_arguments_become_a_readable_tool_error() -> None:
    reg = ToolRegistry(context=None)
    reg.register(Tool("echo", "echoes", _Echo, _echo))
    with pytest.raises(ToolError, match=r"invalid arguments for echo: text:"):
        reg.call("echo", {})


def test_unknown_tool_lists_what_exists_and_duplicates_are_rejected() -> None:
    reg = ToolRegistry(context=None)
    reg.register(Tool("echo", "echoes", _Echo, _echo))
    with pytest.raises(ToolError, match="available: echo"):
        reg.call("nope", {})
    with pytest.raises(ValueError, match="duplicate"):
        reg.register(Tool("echo", "again", _Echo, _echo))


def test_specs_carry_name_description_and_json_schema() -> None:
    reg = ToolRegistry(context=None)
    reg.register(Tool("echo", "echoes", _Echo, _echo))
    [spec] = reg.specs()
    assert spec["name"] == "echo" and spec["description"] == "echoes"
    assert spec["input_schema"]["required"] == ["text"]


class _FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def retrieve(self, query: str, **kw: Any) -> list[RetrievedChunk]:
        self.calls.append({"query": query, **kw})
        return [
            RetrievedChunk(
                chunk_id=7,
                ticker="NVDA",
                form_type="10-Q",
                filed_at="2026-08-26",
                section="Risk Factors",
                text="x" * 3000,
                rrf_score=0.1,
                lexical_rank=1,
                semantic_rank=2,
                accession="0001045810-26-000075",
            )
        ]


class _Pool:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.last: tuple[str, tuple[Any, ...]] | None = None

    def connection(self) -> _Pool:
        return self

    def __enter__(self) -> _Pool:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> _Pool:
        self.last = (sql, params)
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


def test_search_filings_passes_filters_and_truncates_long_passages() -> None:
    retriever = _FakeRetriever()
    reg = build_registry(ToolContext(retriever=retriever, pool=None))  # type: ignore[arg-type]
    out = reg.call(
        "search_filings", {"query": "export controls", "ticker": "NVDA", "form_type": "10-Q"}
    )
    assert retriever.calls == [
        {"query": "export controls", "top_k": 5, "ticker": "NVDA", "form_type": "10-Q"}
    ]
    [p] = out["passages"]
    assert p["accession"] == "0001045810-26-000075" and len(p["text"]) == 1500


def test_search_filings_rejects_bad_arguments() -> None:
    reg = build_registry(ToolContext(retriever=_FakeRetriever(), pool=None))  # type: ignore[arg-type]
    with pytest.raises(ToolError, match="form_type"):
        reg.call("search_filings", {"query": "export controls", "form_type": "8-K"})
    with pytest.raises(ToolError, match="top_k"):
        reg.call("search_filings", {"query": "export controls", "top_k": 99})


def test_list_filings_uppercases_the_ticker_and_shapes_rows() -> None:
    pool = _Pool([("AAPL", "10-K", "0000320193-26-000026", "2026-09-26", "2026-11-03")])
    reg = build_registry(ToolContext(retriever=_FakeRetriever(), pool=pool))  # type: ignore[arg-type]
    out = reg.call("list_filings", {"ticker": "aapl"})
    assert pool.last is not None and pool.last[1] == ("AAPL", "AAPL")
    assert out["filings"][0] == {
        "ticker": "AAPL",
        "form_type": "10-K",
        "accession": "0000320193-26-000026",
        "period_end": "2026-09-26",
        "filed_at": "2026-11-03",
    }
