"""Leakage controls for the embedder fine-tune (evals/finetune/PROTOCOL.md).

Pure functions plus one DB loader. The training set may only contain chunks OUTSIDE the exclusion set:
evaluation evidence chunks, their neighbours, v4 sampling candidates, and near-duplicates of any of those.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from evals.matching import normalize
from evals.schema import EvidenceAnchor

SHINGLE_N = 5
NEAR_DUP_JACCARD = 0.5


@dataclass(frozen=True)
class Chunk:
    id: int
    document_id: int
    accession: str
    section: str
    seq: int
    text: str


def shingles(text: str, n: int = SHINGLE_N) -> frozenset[tuple[str, ...]]:
    words = normalize(re.sub(r"[^\w\s]", " ", text)).split()
    if len(words) < n:
        return frozenset({tuple(words)}) if words else frozenset()
    return frozenset(tuple(words[i : i + n]) for i in range(len(words) - n + 1))


def jaccard(a: frozenset[tuple[str, ...]], b: frozenset[tuple[str, ...]]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def evidence_chunk_ids(chunks: Iterable[Chunk], anchors: Sequence[EvidenceAnchor]) -> set[int]:
    """Chunks of an anchor's filing that contain its snippet (the same test the evals use to score a hit)."""
    wanted: dict[str, list[str]] = {}
    for a in anchors:
        wanted.setdefault(a.accession, []).append(normalize(a.snippet_hint))
    out: set[int] = set()
    for c in chunks:
        hints = wanted.get(c.accession)
        if hints and any(h in normalize(c.text) for h in hints):
            out.add(c.id)
    return out


def skipped_ids_from_header(yaml_text: str) -> set[int]:
    """Chunk ids listed as skipped candidates in a held-out YAML header ('#   9037  AAPL 10-Q   boilerplate ...')."""
    return {
        int(m.group(1))
        for m in re.finditer(r"^#\s+(\d{3,6})\s+(?:AAPL|JPM|NVDA)\b", yaml_text, re.M)
    }


def neighbour_ids(chunks: Sequence[Chunk], centre_ids: set[int]) -> set[int]:
    by_pos = {(c.document_id, c.section, c.seq): c.id for c in chunks}
    out: set[int] = set()
    for c in chunks:
        if c.id in centre_ids:
            for d in (-1, 1):
                nid = by_pos.get((c.document_id, c.section, c.seq + d))
                if nid is not None:
                    out.add(nid)
    return out


def near_duplicate_ids(
    chunks: Sequence[Chunk], seed_ids: set[int], threshold: float = NEAR_DUP_JACCARD
) -> set[int]:
    """Any chunk (any document) whose shingle Jaccard with a seed chunk is >= threshold."""
    sh = {c.id: shingles(c.text) for c in chunks}
    seeds = [sh[i] for i in seed_ids if i in sh]
    out: set[int] = set()
    for c in chunks:
        if c.id in seed_ids:
            continue
        s = sh[c.id]
        if any(jaccard(s, t) >= threshold for t in seeds):
            out.add(c.id)
    return out


def exclusion_set(
    chunks: Sequence[Chunk], anchors: Sequence[EvidenceAnchor], extra_ids: set[int]
) -> set[int]:
    core = evidence_chunk_ids(chunks, anchors) | extra_ids
    with_neighbours = core | neighbour_ids(chunks, core)
    return with_neighbours | near_duplicate_ids(chunks, with_neighbours)
