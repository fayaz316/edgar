"""Edgar Analyst gateway — Phase 1: /ask with cited answers.

Expert bar held from commit one: typed configs, structured JSON logs with
request correlation, liveness/readiness split, and grounded-answer contract
(cite or refuse — dangling citations are suppressed, not shown).
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Literal

import psycopg
import structlog
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from psycopg_pool import ConnectionPool
from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from services.agent.llm import GeminiLLM
from services.embeddings import EmbeddingError, make_embedder
from services.gateway.agent_api import STATIC
from services.gateway.agent_api import router as agent_router
from services.gateway.answer import SYSTEM_PROMPT, GroundedAnswer, build_passages, validate_answer
from services.gateway.retrieval import Retriever
from services.gateway.security import (
    SECURITY_HEADERS,
    UI_CSP,
    KeyStore,
    RateLimiter,
    Security,
    authenticated,
    parse_keys,
)
from services.tools.filings import ToolContext, build_registry

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
    embedder: str = "local"  # local | gemini — must match the model the corpus was embedded with
    database_url: str = Field(
        default="", validation_alias=AliasChoices("EA_DATABASE_URL", "DATABASE_URL")
    )
    gemini_api_key: str = Field(
        default="", validation_alias=AliasChoices("EA_GEMINI_API_KEY", "GEMINI_API_KEY")
    )
    # security (docs/security/threat-model.md)
    api_keys: str = (
        ""  # "name:sha256hex,name2:sha256hex"; create with `python -m services.gateway.keys NAME`
    )
    auth: Literal["on", "off"] = "on"  # "off" is only accepted when environment == "dev"
    rate_per_min: int = Field(default=20, ge=1)  # calls per key per minute on spending endpoints
    agent_daily_cap: int = Field(default=200, ge=1)  # agent runs per key per UTC day
    agent_max_seconds: float = Field(default=120.0, gt=0)  # wall-clock budget for one agent run


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
    # Pooled + autocommit: each request borrows its own connection, and a failed
    # statement can't leave a shared connection stuck in an aborted transaction
    # (which a single long-lived non-autocommit connection would, until restart).
    pool = ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=5,
        kwargs={"autocommit": True},
        timeout=10,  # max wait for a free connection; PoolTimeout -> 503 instead of a 30s hang
        open=False,
    )
    pool.open(wait=True, timeout=15)
    app.state.security = _build_security()
    genai_client = genai.Client(api_key=settings.gemini_api_key)
    app.state.pool = pool
    app.state.genai = genai_client
    embedder = make_embedder(settings.embedder, api_key=settings.gemini_api_key)
    # fail fast on a model/corpus mismatch: otherwise every /ask silently finds nothing
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT count(*) FROM chunks WHERE embedding_model = %s", (embedder.model_id,)
        ).fetchone()
    if not row or row[0] == 0:
        raise RuntimeError(
            f"no chunks embedded with {embedder.model_id}: run `make embed` or set EA_EMBEDDER"
        )
    app.state.retriever = Retriever(pool, embedder)
    app.state.registry = build_registry(ToolContext(retriever=app.state.retriever, pool=pool))
    app.state.agent_llm = GeminiLLM(settings.gemini_api_key)
    app.state.agent_max_seconds = settings.agent_max_seconds
    log.info(
        "startup",
        environment=settings.environment,
        generation_model=GENERATION_MODEL,
        embedding_model=embedder.model_id,
    )
    yield
    pool.close()
    log.info("shutdown")


def _build_security() -> Security:
    """Fail closed: production never starts without keys, and auth can only be switched off in dev."""
    if settings.auth == "off":
        if settings.environment != "dev":
            raise RuntimeError("EA_AUTH=off is only allowed when EA_ENVIRONMENT=dev")
        log.warning("auth_disabled", note="dev only")
        return Security.open()
    keys = KeyStore(parse_keys(settings.api_keys))
    if not len(keys):
        raise RuntimeError(
            "no API keys configured: run `uv run python -m services.gateway.keys NAME` and set "
            "EA_API_KEYS (or EA_AUTH=off with EA_ENVIRONMENT=dev for local use)"
        )
    return Security(keys, RateLimiter(settings.rate_per_min, settings.agent_daily_cap))


_docs = (
    settings.environment != "prod"
)  # no interactive API docs (they load third-party scripts) in prod
app = FastAPI(
    title="Edgar Analyst Gateway",
    version="0.4.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)
app.include_router(agent_router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.path == "/" or request.url.path.startswith("/static"):
        response.headers["content-security-policy"] = UI_CSP
    return response


@app.middleware("http")
async def observability(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach request id + emit one structured access line per request."""
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    structlog.contextvars.clear_contextvars()  # no request_id bleed between requests
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
def readyz(request: Request) -> JSONResponse:
    """Readiness: safe to receive traffic = the database answers. 503 otherwise, so a
    load balancer stops routing here instead of serving 500s."""
    pool: ConnectionPool | None = getattr(request.app.state, "pool", None)
    if pool is None:
        return JSONResponse({"status": "not_ready", "reason": "pool not initialised"}, 503)
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as exc:
        log.warning("readyz_db_failed", error=str(exc)[:120])
        return JSONResponse({"status": "not_ready", "reason": "database unavailable"}, 503)
    return JSONResponse({"status": "ready"})


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, request: Request, caller: str = Depends(authenticated)) -> AskResponse:
    # Plain `def` on purpose: FastAPI runs it in a worker thread, so the blocking
    # DB + Gemini calls below don't freeze the event loop for other requests.
    retriever: Retriever = request.app.state.retriever
    client: genai.Client = request.app.state.genai

    try:
        chunks = retriever.retrieve(req.question, top_k=req.top_k, ticker=req.ticker)
    except EmbeddingError as exc:  # upstream embedding failure (e.g. 429) -> 502, not 500
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except psycopg.Error as exc:
        log.error("retrieval_db_failed", error=str(exc)[:200])
        raise HTTPException(status_code=503, detail="database unavailable") from exc
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
        caller=caller,
        question_len=len(req.question),
        question_hash=hashlib.sha256(req.question.encode()).hexdigest()[:8],
        refused=grounded.refused,
        n_cited=len(citations),
        dangling=grounded.dangling_citations,
    )
    return AskResponse(
        answer=grounded.answer,
        refused=grounded.refused,
        citations=citations,
        retrieval=[
            f"lex={c.lexical_rank} sem={c.semantic_rank} {c.ticker}/{c.section}" for c in chunks
        ],
        model=GENERATION_MODEL,
    )
