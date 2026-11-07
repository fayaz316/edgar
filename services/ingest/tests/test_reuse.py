"""Embedding-reuse planning: the cost-saving core of re-ingest, tested without a DB."""

from __future__ import annotations

from services.ingest.parse import Chunk
from services.ingest.run_ingest import plan_chunk_rows

VEC = "[0.1,0.2]"
MODEL = "BAAI/bge-base-en-v1.5@a5beb1e3"


def test_unchanged_text_reuses_embedding_even_if_section_relabeled() -> None:
    chunks = [
        Chunk(section="Financial Statements", seq=0, text="Three customers were 16% of revenue.")
    ]
    rows, reused = plan_chunk_rows(7, chunks, {"Three customers were 16% of revenue.": VEC}, MODEL)
    assert reused == 1
    assert rows == [
        (7, "Financial Statements", 0, "Three customers were 16% of revenue.", VEC, MODEL)
    ]


def test_new_or_edited_text_needs_embedding_and_carries_no_model_tag() -> None:
    chunks = [Chunk("MD&A", 0, "old text"), Chunk("MD&A", 1, "brand new table row text")]
    rows, reused = plan_chunk_rows(1, chunks, {"old text": VEC}, MODEL)
    assert reused == 1
    assert [r[4] for r in rows] == [VEC, None]
    # CHECK constraint: a vector and its model tag are present together or not at all
    assert [r[5] for r in rows] == [MODEL, None]


def test_empty_cases() -> None:
    assert plan_chunk_rows(1, [], {"x": VEC}, MODEL) == ([], 0)
    rows, reused = plan_chunk_rows(1, [Chunk("MD&A", 0, "t")], {}, MODEL)
    assert (reused, rows[0][4], rows[0][5]) == (0, None, None)
