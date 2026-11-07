"""Answer-grounding unit tests — pure functions, CI-safe."""

from __future__ import annotations

from services.gateway.answer import (
    SYSTEM_PROMPT,
    build_passages,
    extract_citations,
    validate_answer,
)
from services.gateway.retrieval import RetrievedChunk


def _chunk(cid: int, text: str = "passage body", section: str = "Risk Factors") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        ticker="NVDA",
        form_type="10-Q",
        filed_at="2026-08-26",
        section=section,
        text=text,
        rrf_score=0.03,
        lexical_rank=1,
        semantic_rank=1,
        accession="0001045810-26-000075",
    )


def test_build_passages_numbered_with_headers() -> None:
    out = build_passages([_chunk(1), _chunk(2, section="MD&A")])
    assert out.startswith("[1] NVDA 10-Q filed 2026-08-26 — Risk Factors")
    assert "[2] NVDA 10-Q filed 2026-08-26 — MD&A" in out


def test_extract_citations_ordered_dedup() -> None:
    assert extract_citations("a [2] b [1] c [2] [10]") == [2, 1, 10]
    assert extract_citations("no citations here") == []


def test_validate_good_answer() -> None:
    g = validate_answer("Revenue concentration is 16% [1] and rising [1][3].", 3)
    assert not g.refused
    assert g.cited_passages == [1, 3]
    assert g.dangling_citations == []


def test_validate_dangling_citation_refuses() -> None:
    g = validate_answer("Something [7].", 3)
    assert g.refused
    assert g.dangling_citations == [7]


def test_validate_uncited_answer_refuses() -> None:
    g = validate_answer("NVIDIA revenue grew 12%.", 3)
    assert g.refused  # uncited claims suppressed — correctness-critical vertical


def test_explicit_refusal_passes_through() -> None:
    g = validate_answer("INSUFFICIENT_CONTEXT — passages lack guidance data.", 3)
    assert g.refused
    assert g.cited_passages == []


def test_system_prompt_states_contract() -> None:
    assert "ONLY" in SYSTEM_PROMPT and "INSUFFICIENT_CONTEXT" in SYSTEM_PROMPT
