"""Pure matching + metric helpers for retrieval evals (no IO — fully unit-testable).

An anchor "hits" a retrieved chunk when the chunk is from the same filing
(accession) AND contains the anchor's snippet_hint (whitespace/case-insensitive).
Section is deliberately NOT part of the hit test: section labels come from a
heuristic parser that we are still fixing, and an eval must not move when the
labels do. Section agreement is reported separately as a diagnostic.
"""

from __future__ import annotations

from collections.abc import Sequence

from evals.schema import EvidenceAnchor

RankedChunk = tuple[str, str, str]  # (accession, section, text), best first


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


def anchor_matches(chunk: RankedChunk, anchor: EvidenceAnchor) -> bool:
    accession, _section, text = chunk
    return accession == anchor.accession and normalize(anchor.snippet_hint) in normalize(text)


def first_hit_rank(chunks: Sequence[RankedChunk], anchors: Sequence[EvidenceAnchor]) -> int | None:
    """1-based rank of the first chunk matching ANY anchor; None = miss."""
    for rank, chunk in enumerate(chunks, start=1):
        if any(anchor_matches(chunk, a) for a in anchors):
            return rank
    return None


def anchors_covered(
    chunks: Sequence[RankedChunk], anchors: Sequence[EvidenceAnchor], k: int
) -> tuple[int, int]:
    """(anchors found in top-k, total anchors) — recall for multi-evidence questions."""
    top = chunks[:k]
    found = sum(1 for a in anchors if any(anchor_matches(c, a) for c in top))
    return found, len(anchors)


def section_agrees(chunks: Sequence[RankedChunk], anchors: Sequence[EvidenceAnchor]) -> bool | None:
    """Diagnostic: does the hitting chunk carry the section the golden anchor names?
    None when nothing hit."""
    for chunk in chunks:
        for a in anchors:
            if anchor_matches(chunk, a):
                return chunk[1] == a.section
    return None


def summarize(ranks: Sequence[int | None], ks: Sequence[int] = (1, 3, 5, 8)) -> dict[str, float]:
    """hit@k and MRR over per-question first-hit ranks."""
    n = len(ranks)
    if n == 0:
        return {}
    out: dict[str, float] = {
        f"hit@{k}": sum(1 for r in ranks if r is not None and r <= k) / n for k in ks
    }
    out["mrr"] = sum(1.0 / r for r in ranks if r is not None) / n
    return out
