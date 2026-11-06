"""Edgar Analyst gateway — Phase 1: /ask with cited answers.

Expert bar held from commit one: typed configs, structured JSON logs with
request correlation, liveness/readiness split, and grounded-answer contract
(cite or refuse — dangling citations are suppressed, not shown).
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import psycopg
import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from google import genai
from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from services.gateway.answer import SYSTEM_PROMPT, GroundedAnswer, build_passages, validate_answer
from services.gateway.retrieval import Retriever

load_dotenv()  # shared repo .env; Settings picks only its aliased keys

GENERATION_MODEL = "gemini-3.1-flash-lite"  # free tier: 15 RPM / 500 RPD


class Settings(BaseSettings):
    """Runtime config. App-specific vars use the EA_ prefix; shared dev-infra
    vars (DATABASE_URL, GEMINI_API_KEY) are read via explicit aliases.

    extra="ignore": the repo-root .env also carries dev-infra secrets owned
    by other services — this app ignores what isn't its own.
    """

    model_config = SettingsConfigDict(env_prefix="EA_", env_file=".env", extra="ignore")

    environment: str = "dev"  # dev | prod — drives log verbosity and feature gates
    log_level: str = "INFO"
    database_url: str = Field(default="", validation_alias=AliasChoices("EA_DATABASE_URL", "DATABASE_URL"))
    gemini_api_key: str = Field(default="", validation_alias=AliasChoices("EA_GEMINI_API_KEY", "GEMINI_API_KEY"))


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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open expensive clients once; close cleanly on shutdown."""
    if not settings.database_url or not settings.gemini_api_key:
        raise RuntimeError("EA_DATABASE_URL / GEMINI_API_KEY required")
    conn = psycopg.connect(settings.database_url)
    genai_client = genai.Client(api_key=settings.gemini_api_key)
    app.state.conn = conn
    app.state.genai = genai_client
    app.state.retriever = Retriever(conn, genai_client)
    log.info("startup", environment=settings.environment, generation_model=GENERATION_MODEL)
    yield
    conn.close()
    log.info("shutdown")


app = FastAPI(title="Edgar Analyst Gateway", version="0.2.0", lifespan=lifespan)


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


class AskRequest(BaseModel):
    question: str = Field(min_length=8, max_length=500)
    ticker: str | None = Field(default=None, min_length=1, max_length=6)
    top_k: int = Field(default=8, ge=3, le=12)


class Citation(BaseModel):
    passage: int
    chunk_id: int
    ticker: str
    form_type: str
    filed_at: str
    section: str
    excerpt: str  # first 200 chars — enough for a human to verify


class AskResponse(BaseModel):
    answer: str
    refused: bool
    citations: list[Citation]
    retrieval: list[str]  # provenance line per retrieved chunk (lex/sem ranks)
    model: str


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: process is up. Never checks dependencies (that's readiness)."""
    return {"status": "ok", "env": settings.environment}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    """Readiness: safe to receive traffic. Dependency checks grow here per phase."""
    return {"status": "ready"}


@app.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest, request: Request) -> AskResponse:
    retriever: Retriever = request.app.state.retriever
    client: genai.Client = request.app.state.genai

    chunks = retriever.retrieve(req.question, top_k=req.top_k, ticker=req.ticker)
    if not chunks:
        return AskResponse(
            answer="INSUFFICIENT_CONTEXT — no passages retrieved for this query.",
            refused=True,
            citations=[],
            retrieval=[],
            model=GENERATION_MODEL,
        )

    prompt = f"Question: {req.question}\n\nPassages:\n\n{build_passages(chunks)}"
    try:
        gen = client.models.generate_content(
            model=GENERATION_MODEL,
            contents=prompt,
            config={"system_instruction": SYSTEM_PROMPT, "temperature": 0.0},
        )
        raw = (gen.text or "").strip()
    except Exception as exc:  # upstream model failure surfaces as 502, not a lie
        raise HTTPException(status_code=502, detail=f"generation failed: {str(exc)[:150]}") from exc

    grounded: GroundedAnswer = validate_answer(raw, n_passages=len(chunks))
    cited_map = {n: chunks[n - 1] for n in grounded.cited_passages}
    citations = [
        Citation(
            passage=n,
            chunk_id=c.chunk_id,
            ticker=c.ticker,
            form_type=c.form_type,
            filed_at=c.filed_at,
            section=c.section,
            excerpt=c.text[:200],
        )
        for n, c in cited_map.items()
    ]
    log.info(
        "ask",
        question=req.question[:80],
        refused=grounded.refused,
        n_cited=len(citations),
        dangling=grounded.dangling_citations,
    )
    return AskResponse(
        answer=grounded.answer,
        refused=grounded.refused,
        citations=citations,
        retrieval=[f"lex={c.lexical_rank} sem={c.semantic_rank} {c.ticker}/{c.section}" for c in chunks],
        model=GENERATION_MODEL,
    )
