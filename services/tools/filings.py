"""Filing tools: search passages, list what is in the corpus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from services.gateway.retrieval import Retriever
from services.tools.registry import Tool, ToolRegistry

MAX_PASSAGE_CHARS = 1500  # keeps a tool result small enough to sit in a model's context


@dataclass
class ToolContext:
    retriever: Retriever
    pool: Any  # psycopg ConnectionPool; Any so tests can pass a fake


class SearchFilingsParams(BaseModel):
    query: str = Field(min_length=3, max_length=300, description="What to look for, in plain words")
    ticker: str | None = Field(default=None, description="Restrict to one company, e.g. NVDA")
    form_type: Literal["10-K", "10-Q"] | None = Field(
        default=None, description="Restrict to annual (10-K) or quarterly (10-Q) filings"
    )
    top_k: int = Field(default=5, ge=1, le=12, description="How many passages to return")


class ListFilingsParams(BaseModel):
    ticker: str | None = Field(default=None, description="Restrict to one company, e.g. AAPL")


def search_filings(ctx: ToolContext, p: SearchFilingsParams) -> dict[str, Any]:
    chunks = ctx.retriever.retrieve(p.query, top_k=p.top_k, ticker=p.ticker, form_type=p.form_type)
    return {
        "passages": [
            {
                "chunk_id": c.chunk_id,
                "ticker": c.ticker,
                "form_type": c.form_type,
                "filed_at": c.filed_at,
                "accession": c.accession,
                "section": c.section,
                "text": c.text[:MAX_PASSAGE_CHARS],
            }
            for c in chunks
        ]
    }


def list_filings(ctx: ToolContext, p: ListFilingsParams) -> dict[str, Any]:
    sql = (
        "SELECT ticker, form_type, accession, period_end::text, filed_at::date::text "
        "FROM documents WHERE (%s::text IS NULL OR ticker = %s) ORDER BY ticker, filed_at"
    )
    ticker = p.ticker.upper() if p.ticker else None
    with ctx.pool.connection() as conn:
        rows = conn.execute(sql, (ticker, ticker)).fetchall()
    return {
        "filings": [
            {
                "ticker": r[0],
                "form_type": r[1],
                "accession": r[2],
                "period_end": r[3],
                "filed_at": r[4],
            }
            for r in rows
        ]
    }


def build_registry(ctx: ToolContext) -> ToolRegistry:
    registry = ToolRegistry(ctx)
    registry.register(
        Tool(
            name="search_filings",
            description=(
                "Search SEC 10-K/10-Q filings (Apple, JPMorgan, NVIDIA) and return the most "
                "relevant passages with their company, form, filing date and section. Use it "
                "before stating any fact about a filing, and cite the passages you rely on."
            ),
            params=SearchFilingsParams,
            handler=search_filings,  # type: ignore[arg-type]
        )
    )
    registry.register(
        Tool(
            name="list_filings",
            description=(
                "List the filings in the corpus (ticker, form type, accession, period end, filing "
                "date). Use it to see which companies and periods exist before searching."
            ),
            params=ListFilingsParams,
            handler=list_filings,  # type: ignore[arg-type]
        )
    )
    return registry
