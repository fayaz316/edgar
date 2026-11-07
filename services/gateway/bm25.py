"""BM25 scoring for the keyword leg (pure functions, no IO).

Why: Postgres full-text ranking (`ts_rank_cd`) has no inverse-document-frequency, so a word found
in half the corpus ("December", "preferred") counts like a rare, telling one. BM25 weights each
query term by how rare it is and damps repeats and long chunks.

Constants are the textbook defaults (Robertson et al.). They are fixed on purpose: see
evals/golden/HELDOUT_PROTOCOL.md, Addendum D. Do not tune them against the eval sets.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping

K1 = 1.2
B = 0.75

# (chunk_id, lexeme, term frequency in the chunk, chunk length in lexemes)
TermRow = tuple[int, str, int, int]


def idf(n_docs: int, df: int) -> float:
    """Lucene-style IDF: always positive, even for terms in most chunks."""
    return math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))


def bm25_scores(
    rows: Iterable[TermRow], df: Mapping[str, int], n_docs: int, avgdl: float
) -> dict[int, float]:
    scores: dict[int, float] = defaultdict(float)
    for chunk_id, lexeme, tf, dl in rows:
        norm = tf + K1 * (1.0 - B + B * dl / avgdl) if avgdl > 0 else tf + K1
        scores[chunk_id] += idf(n_docs, df[lexeme]) * tf * (K1 + 1.0) / norm
    return dict(scores)


def bm25_rank(
    rows: Iterable[TermRow], df: Mapping[str, int], n_docs: int, avgdl: float
) -> list[int]:
    """Chunk ids, best first. Ties break on the lower id so results are deterministic."""
    scores = bm25_scores(rows, df, n_docs, avgdl)
    return [cid for cid, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]
