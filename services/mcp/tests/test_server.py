from __future__ import annotations

import asyncio
from typing import Any

from services.mcp.server import build_server
from services.tools.filings import ToolContext, build_registry
from services.tools.tests.test_registry import _FakeRetriever, _Pool


def _server() -> tuple[Any, Any, _FakeRetriever]:
    retriever = _FakeRetriever()
    registry = build_registry(ToolContext(retriever=retriever, pool=_Pool([])))  # type: ignore[arg-type]
    return build_server(registry), registry, retriever


def test_mcp_tools_match_the_registry_exactly() -> None:
    """Drift guard: a tool added to the registry but not the server (or vice versa) fails here."""
    server, registry, _ = _server()
    tools = asyncio.run(server.list_tools())
    assert sorted(t.name for t in tools) == registry.names()
    by_name = {t.name: t for t in tools}
    for name in registry.names():
        assert by_name[name].description == registry.get(name).description


def test_mcp_search_tool_reaches_the_retriever_with_its_arguments() -> None:
    server, _, retriever = _server()
    result = asyncio.run(
        server.call_tool("search_filings", {"query": "export controls", "form_type": "10-K"})
    )
    assert retriever.calls[0]["form_type"] == "10-K"
    assert not getattr(result, "is_error", False)
