"""Cross-encoder reranking of fused candidates (Phase 1: "hybrid search + rerank").

A bi-encoder embeds the question and each chunk separately; a cross-encoder reads the pair
together and scores relevance directly, which is slower but sharper. It can only reorder what
the first stage already retrieved, so it helps targets inside the candidate pool, not outside.

Specified before any run in evals/golden/HELDOUT_PROTOCOL.md, Addendum G: one fixed model, text
only, no blending with the fused score. Off unless the guard there passes (ADR 0011).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any, Protocol

RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANK_POOL = 30  # how many fused candidates are rescored


class Reranker(Protocol):
    def score(self, query: str, texts: Sequence[str]) -> list[float]: ...


def reorder(scores: Sequence[float]) -> list[int]:
    """Indices best score first; ties keep the original (fused) order."""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


class CrossEncoderReranker:
    """Lazy-loads the model (needs the `local-embed` dependency group: torch + sentence-transformers)."""

    def __init__(self, model_name: str = RERANK_MODEL) -> None:
        self.model_name = model_name
        self.timings: list[float] = []  # seconds per score() call, for latency reporting
        self._model: Any = None

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        if self._model is None:
            from sentence_transformers import CrossEncoder  # heavy import, only when used

            self._model = CrossEncoder(self.model_name)
        start = time.perf_counter()
        raw = self._model.predict([(query, t) for t in texts], show_progress_bar=False)
        self.timings.append(time.perf_counter() - start)
        return [float(x) for x in raw]
