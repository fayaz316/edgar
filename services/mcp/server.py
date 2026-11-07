"""MCP server: exposes the tool registry to any MCP client (Claude Desktop, an agent, ...).

Run:  uv run --group local-embed python -m services.mcp.server      (stdio transport)

The tool names and descriptions come from the registry, so there is one definition. The wrappers
below only give the MCP SDK typed signatures to build schemas from; a test fails if the two drift.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from services.tools.registry import ToolRegistry


def build_server(registry: ToolRegistry) -> MCPServer:
    server = MCPServer(
        name="edgar-analyst",
        instructions=(
            "Citation-grounded research over SEC 10-K/10-Q filings. Search before answering; "
            "cite the passages you use; say so when the filings do not contain the answer."
        ),
    )

    @server.tool(name="search_filings", description=registry.get("search_filings").description)
    def search_filings(
        query: str,
        ticker: str | None = None,
        form_type: Literal["10-K", "10-Q"] | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        return registry.call(
            "search_filings",
            {"query": query, "ticker": ticker, "form_type": form_type, "top_k": top_k},
        )

    @server.tool(name="list_filings", description=registry.get("list_filings").description)
    def list_filings(ticker: str | None = None) -> dict[str, Any]:
        return registry.call("list_filings", {"ticker": ticker})

    return server


def main() -> None:
    # Imports kept local: building the real context loads the embedding model (seconds).
    from dotenv import load_dotenv
    from psycopg_pool import ConnectionPool

    from services.embeddings import make_embedder
    from services.gateway.retrieval import Retriever
    from services.tools.filings import ToolContext, build_registry

    load_dotenv(".env")
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("EA_DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL missing (check .env)")
    embedder = make_embedder(
        os.environ.get("EA_EMBEDDER", "local"), api_key=os.environ.get("GEMINI_API_KEY")
    )
    pool = ConnectionPool(dsn, min_size=1, max_size=3, kwargs={"autocommit": True}, open=True)
    registry = build_registry(ToolContext(retriever=Retriever(pool, embedder), pool=pool))
    build_server(registry).run("stdio")


if __name__ == "__main__":
    main()
