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
    Retriever(pool, emb, keyword="and").retrieve("customer concentration risk", **kwargs)  # type: ignore[arg-type]
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


def test_form_type_hint_in_question_scopes_both_legs() -> None:
    pool, _ = _run_q("What did the latest 10-Q say about credit losses?")
    for sql, params in pool.log[:2]:  # the scoped lexical + semantic queries
        assert "d.form_type = %s" in sql
        assert "max(d2.filed_at)" in sql
        assert params.count("10-Q") == 2  # once for the filter, once inside the 'latest' subquery


def test_no_hint_means_no_filing_filter() -> None:
    pool, _ = _run(LOCAL_MODEL_ID)
    assert all("d.form_type = %s" not in sql for sql, _p in pool.log)


def test_infer_filing_false_ignores_the_question() -> None:
    pool, emb = RecordingPool(), FakeEmbedder(LOCAL_MODEL_ID)
    Retriever(pool, emb, keyword="and").retrieve("latest 10-Q", infer_filing=False)  # type: ignore[arg-type]
    assert all("d.form_type = %s" not in sql for sql, _p in pool.log)


def test_empty_scoped_search_falls_back_to_unscoped() -> None:
    pool, _ = _run_q("latest 10-Q credit losses")
    assert len(pool.log) == 4  # scoped lexical+semantic found nothing -> repeated unscoped
    assert all("d.form_type = %s" not in sql for sql, _p in pool.log[2:])


def _run_q(question: str) -> tuple[RecordingPool, FakeEmbedder]:
    pool, emb = RecordingPool(), FakeEmbedder(LOCAL_MODEL_ID)
    Retriever(pool, emb, keyword="and").retrieve(question)  # type: ignore[arg-type]
    return pool, emb


def test_default_keyword_leg_is_bm25() -> None:
    pool, emb = RecordingPool(), FakeEmbedder(LOCAL_MODEL_ID)
    Retriever(pool, emb).retrieve("customer concentration risk")  # type: ignore[arg-type]
    assert "tsvector_to_array" in pool.log[0][0]


def test_keyword_and_is_the_plain_websearch_query() -> None:
    pool, _ = _run(LOCAL_MODEL_ID)
    assert "' | '" not in pool.log[0][0]


def test_keyword_or_ors_the_query_terms() -> None:
    pool, emb = RecordingPool(), FakeEmbedder(LOCAL_MODEL_ID)
    Retriever(pool, emb, keyword="or").retrieve("x y")  # type: ignore[arg-type]
    assert "' | '" in pool.log[0][0]  # & -> | on the normalised tsquery


def test_bm25_mode_still_runs_the_semantic_leg_when_no_terms_match() -> None:
    pool, emb = RecordingPool(), FakeEmbedder(LOCAL_MODEL_ID)
    Retriever(pool, emb).retrieve("and the of")  # type: ignore[arg-type]
    assert "tsvector_to_array" in pool.log[0][0]  # lexeme extraction ran first
    assert len(pool.log) == 2  # no lexemes -> no candidate query; semantic leg still ran
    assert "c.embedding <=>" in pool.log[1][0]


class _ScriptedCursor(_Cursor):
    """Returns canned rows in call order, so the BM25 path can be exercised without a database."""

    def __init__(
        self, log: list[tuple[str, list[Any]]], script: list[list[tuple[Any, ...]]]
    ) -> None:
        super().__init__(log)
        self._script = script
        self._current: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: list[Any] | None = None) -> None:
        self._log.append((sql, params or []))
        self._current = self._script.pop(0) if self._script else []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._current

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._current[0] if self._current else None


class _ScriptedConn(_Conn):
    def __init__(
        self, log: list[tuple[str, list[Any]]], script: list[list[tuple[Any, ...]]]
    ) -> None:
        super().__init__(log)
        self._script = script

    def cursor(self) -> _ScriptedCursor:
        return _ScriptedCursor(self._log, self._script)


class ScriptedPool(RecordingPool):
    def __init__(self, script: list[list[tuple[Any, ...]]]) -> None:
        super().__init__()
        self._script = script

    @contextmanager
    def connection(self) -> Iterator[_ScriptedConn]:
        yield _ScriptedConn(self.log, self._script)


def test_bm25_ranks_by_idf_and_applies_the_scope_filters_afterwards() -> None:
    def meta(cid: int) -> tuple[Any, ...]:
        return (cid, "NVDA", "10-Q", "2026-08-26", "MD&A", f"text {cid}", f"acc-{cid}")

    script: list[list[tuple[Any, ...]]] = [
        [("export",), ("licens",)],  # 1. query lexemes
        # 2. (chunk, lexeme, tf, dl): chunk 10 has the rare term, chunk 20 only the common one
        [
            (10, "licens", 1, 50),
            (20, "export", 1, 50),
            (21, "export", 1, 50),
            (22, "export", 1, 50),
        ],
        [(1000, 50.0)],  # 3. corpus stats (count, avg length)
        [meta(20), meta(10)],  # 4. scoped metadata, deliberately out of rank order
        [],  # 5. semantic leg
    ]
    pool, emb = ScriptedPool(script), FakeEmbedder(LOCAL_MODEL_ID)
    got = Retriever(pool, emb).retrieve("export license", ticker="nvda")  # type: ignore[arg-type]
    assert next(c.chunk_id for c in got) == 10  # rare-term chunk first despite metadata order
    meta_sql, meta_params = pool.log[3]
    assert "d.ticker = %s" in meta_sql and "NVDA" in meta_params
    assert meta_params[-1][0] == 10  # candidate ids passed in BM25 rank order


def test_product_defaults_are_what_the_eval_gate_protects() -> None:
    """If a default changes, evals/gate.py DEFAULT_CONFIG and the baseline must change with it (ADR required)."""
    import inspect

    from evals.gate import DEFAULT_CONFIG

    pool, emb = RecordingPool(), FakeEmbedder(LOCAL_MODEL_ID)
    retriever = Retriever(pool, emb)  # type: ignore[arg-type]
    assert retriever.keyword == DEFAULT_CONFIG["lexical"]
    assert retriever._reranker is None and DEFAULT_CONFIG["rerank"] is False
    assert inspect.signature(Retriever.retrieve).parameters["infer_filing"].default is True
    assert DEFAULT_CONFIG["filing_hints"] is True
