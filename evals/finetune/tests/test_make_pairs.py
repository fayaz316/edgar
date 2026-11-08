import random

from evals.finetune.exclusion import shingles
from evals.finetune.make_pairs import RANK_HI, RANK_LO, is_val_chunk, pick_negative


def chunk(i: int, doc: int = 1, section: str = "S", text: str | None = None) -> dict:  # type: ignore[type-arg]
    return {
        "id": i,
        "document_id": doc,
        "section": section,
        "text": text or f"unique passage number {i} about topic {i} words words",
    }


def test_negative_comes_from_the_band_and_avoids_same_section_and_near_duplicates() -> None:
    chunks = {i: chunk(i, doc=2 if i % 2 else 3) for i in range(1, 60)}
    chunks[1] = chunk(1, doc=1, section="Risk")
    chunks[20] = chunk(20, doc=1, section="Risk")  # same document + section as the positive
    sh = {i: shingles(c["text"]) for i, c in chunks.items()}
    ranked = list(range(1, 60))
    neg = pick_negative(ranked, chunks[1], chunks, sh, random.Random(0))
    assert neg is not None and RANK_LO <= ranked.index(neg) + 1 <= RANK_HI and neg != 20


def test_no_negative_when_the_band_is_empty() -> None:
    chunks = {i: chunk(i) for i in range(1, 6)}
    sh = {i: shingles(c["text"]) for i, c in chunks.items()}
    assert pick_negative([1, 2, 3, 4, 5], chunks[1], chunks, sh, random.Random(0)) is None


def test_val_split_is_by_chunk_and_stable() -> None:
    assert [is_val_chunk(i) for i in range(50)] == [is_val_chunk(i) for i in range(50)]
    assert 0 < sum(is_val_chunk(i) for i in range(2000)) < 300
