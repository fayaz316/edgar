"""Build the real tool registry from the environment (DB, embedder). Shared by the MCP server
and the agent CLI so both get exactly the same tools wired the same way."""

from __future__ import annotations

import os

from services.tools.registry import ToolRegistry


def registry_from_env() -> ToolRegistry:
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
    return build_registry(ToolContext(retriever=Retriever(pool, embedder), pool=pool))
