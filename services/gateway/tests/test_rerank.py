from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from services.embeddings import LOCAL_MODEL_ID
from services.gateway.rerank import reorder
from services.gateway.retrieval import Retriever
from services.gateway.tests.test_retriever_sql import FakeEmbedder, ScriptedPool


def test_reorder_best_first_and_ties_keep_original_order() -> None:
    assert reorder([0.1, 0.9, 0.5]) == [1, 2, 0]
    assert reorder([0.5, 0.5, 0.9, 0.5]) == [2, 0, 1, 3]
    assert reorder([]) == []


class PreferChunk:
    """Fake reranker: scores the chunk whose text mentions `word` highest."""

    def __init__(self, word: str) -> None:
        self.word = word
        self.seen: list[str] = []

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        self.seen = list(texts)
        return [1.0 if self.word in t else 0.0 for t in texts]


def _row(cid: int) -> tuple[Any, ...]:
    return (cid, "NVDA", "10-Q", "2026-08-26", "MD&A", f"chunk {cid} text", f"acc-{cid}")


def _retriever(reranker: PreferChunk | None) -> Retriever:
    rows = [_row(1), _row(2), _row(3)]
    pool = ScriptedPool([rows, rows])  # lexical leg, semantic leg: identical order -> fused 1,2,3
    return Retriever(
        pool,  # type: ignore[arg-type]
        FakeEmbedder(LOCAL_MODEL_ID),
        keyword="and",
        reranker=reranker,
    )


def test_without_reranker_the_fused_order_is_kept() -> None:
    got = _retriever(None).retrieve("q")
    assert [c.chunk_id for c in got] == [1, 2, 3]
    assert all(c.rerank_score is None for c in got)


def test_reranker_can_promote_a_chunk_from_below_top_k() -> None:
    rr = PreferChunk("chunk 3")
    got = _retriever(rr).retrieve("q", top_k=2)
    assert [c.chunk_id for c in got] == [3, 1]  # chunk 3 was 3rd fused, now first; ties stay fused
    assert got[0].rerank_score == 1.0
    assert len(rr.seen) == 3  # the pool (not just top_k) was rescored
