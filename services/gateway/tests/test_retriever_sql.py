"""The retriever must only search vectors from the ACTIVE model — checked at the SQL level
with a recording fake pool (no database)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from services.embeddings import DIMS, GEMINI_MODEL_ID, LOCAL_MODEL_ID
from services.gateway.retrieval import Retriever


class FakeEmbedder:
    dims = DIMS
    batch_size = 1
    pause_s = 0.0

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.queries: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * DIMS for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.25] * DIMS


class _Cursor:
    def __init__(self, log: list[tuple[str, list[Any]]]) -> None:
        self._log = log

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def execute(self, sql: str, params: list[Any]) -> None:
        self._log.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return []


class _Conn:
    def __init__(self, log: list[tuple[str, list[Any]]]) -> None:
        self._log = log

    def cursor(self) -> _Cursor:
        return _Cursor(self._log)


class RecordingPool:
    def __init__(self) -> None:
        self.log: list[tuple[str, list[Any]]] = []

    @contextmanager
    def connection(self) -> Iterator[_Conn]:
        yield _Conn(self.log)


def _run(model_id: str, **kwargs: Any) -> tuple[RecordingPool, FakeEmbedder]:
    pool, emb = RecordingPool(), FakeEmbedder(model_id)
    Retriever(pool, emb).retrieve("customer concentration risk", **kwargs)  # type: ignore[arg-type]
    return pool, emb


def test_both_legs_filter_on_the_active_model() -> None:
    pool, _ = _run(LOCAL_MODEL_ID)
    assert len(pool.log) == 2
    for sql, _params in pool.log:
        assert "c.embedding_model = %s" in sql
    lexical, semantic = pool.log
    assert lexical[1][:2] == ["customer concentration risk", LOCAL_MODEL_ID]  # query, then model
    assert semantic[1][0] == LOCAL_MODEL_ID  # model first, vector literal last
    assert semantic[1][-1].startswith("[0.250000,")


def test_switching_embedder_changes_the_filter() -> None:
    pool, _ = _run(GEMINI_MODEL_ID)
    assert all(GEMINI_MODEL_ID in params for _sql, params in pool.log)


def test_ticker_filter_composes_after_model_filter() -> None:
    pool, _ = _run(LOCAL_MODEL_ID, ticker="nvda")
    assert pool.log[1][1][:2] == [LOCAL_MODEL_ID, "NVDA"]


def test_query_embedding_comes_from_the_embedder() -> None:
    _, emb = _run(LOCAL_MODEL_ID)
    assert emb.queries == ["customer concentration risk"]
