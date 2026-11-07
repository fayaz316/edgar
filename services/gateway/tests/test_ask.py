"""/ask contract tests with fake retriever + fake Gemini — CI-safe, no network, no DB.

Locks in the product's core promise: cite or refuse, and map upstream failures to
honest status codes (502 upstream / 503 database) instead of leaking 500s.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from services.embeddings import EmbeddingError
from services.gateway.main import app
from services.gateway.retrieval import RetrievedChunk

client = TestClient(app)
QUESTION = "What share of revenue came from the three largest customers?"


def _chunk(
    cid: int, text: str = "Three customers were 16%, 15% and 13% of revenue."
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        ticker="NVDA",
        form_type="10-Q",
        filed_at="2026-08-26",
        section="Financial Statements",
        text=text,
        rrf_score=0.03,
        lexical_rank=1,
        semantic_rank=2,
        accession="0001045810-26-000075",
    )


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk] | None = None, error: Exception | None = None):
        self._chunks = chunks if chunks is not None else []
        self._error = error

    def retrieve(self, query: str, **kwargs: Any) -> list[RetrievedChunk]:
        if self._error:
            raise self._error
        return self._chunks


class FakeGenai:
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.calls = 0
        self._text = text
        self._error = error
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        if self._error:
            raise self._error
        return SimpleNamespace(text=self._text)


@pytest.fixture
def wire() -> Iterator[Any]:
    def _wire(retriever: FakeRetriever, genai_client: FakeGenai) -> None:
        app.state.retriever = retriever
        app.state.genai = genai_client

    yield _wire
    for attr in ("retriever", "genai"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


def _ask() -> Any:
    return client.post("/ask", json={"question": QUESTION})


def test_cited_answer_returns_citations(wire: Any) -> None:
    wire(FakeRetriever([_chunk(7), _chunk(9)]), FakeGenai("Three customers drove 44% [1][2]."))
    r = _ask()
    assert r.status_code == 200
    body = r.json()
    assert body["refused"] is False
    assert [c["chunk_id"] for c in body["citations"]] == [7, 9]
    assert body["citations"][0]["excerpt"].startswith("Three customers")


def test_dangling_citation_is_suppressed(wire: Any) -> None:
    wire(FakeRetriever([_chunk(1)]), FakeGenai("It was 44% [5]."))
    body = _ask().json()
    assert body["refused"] is True
    assert body["citations"] == []
    assert "44%" not in body["answer"]


def test_uncited_answer_is_suppressed(wire: Any) -> None:
    wire(FakeRetriever([_chunk(1)]), FakeGenai("It was 44%."))
    assert _ask().json()["refused"] is True


def test_model_refusal_passes_through(wire: Any) -> None:
    wire(FakeRetriever([_chunk(1)]), FakeGenai("INSUFFICIENT_CONTEXT — nothing on crypto."))
    body = _ask().json()
    assert body["refused"] is True
    assert body["citations"] == []


def test_no_passages_refuses_without_calling_model(wire: Any) -> None:
    gen = FakeGenai("should never be used")
    wire(FakeRetriever([]), gen)
    body = _ask().json()
    assert body["refused"] is True
    assert gen.calls == 0


def test_generation_failure_is_502(wire: Any) -> None:
    wire(FakeRetriever([_chunk(1)]), FakeGenai(error=RuntimeError("429 RESOURCE_EXHAUSTED")))
    assert _ask().status_code == 502


def test_embedding_failure_is_502_not_500(wire: Any) -> None:
    wire(FakeRetriever(error=EmbeddingError("query embedding failed: 429")), FakeGenai("x"))
    r = _ask()
    assert r.status_code == 502
    assert "embedding" in r.json()["detail"]


def test_database_failure_is_503(wire: Any) -> None:
    wire(FakeRetriever(error=psycopg.OperationalError("down")), FakeGenai("x"))
    assert _ask().status_code == 503


def test_short_question_rejected() -> None:
    assert client.post("/ask", json={"question": "hi"}).status_code == 422
