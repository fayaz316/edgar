from __future__ import annotations

from evals.matching import (
    RankedChunk,
    anchor_matches,
    anchors_covered,
    first_hit_rank,
    normalize,
    section_agrees,
    summarize,
)
from evals.schema import EvidenceAnchor

ACC = "0001045810-26-000075"


def _anchor(
    hint: str = "16%, 15%, and 13%", acc: str = ACC, section: str = "Business"
) -> EvidenceAnchor:
    return EvidenceAnchor(accession=acc, section=section, snippet_hint=hint)


def _chunk(text: str, acc: str = ACC, section: str = "Business") -> RankedChunk:
    return (acc, section, text)


def test_normalize_collapses_whitespace_and_case() -> None:
    assert normalize("  Three\n direct   CUSTOMERS ") == "three direct customers"


def test_match_requires_same_accession() -> None:
    assert anchor_matches(_chunk("customers were 16%, 15%, and 13%"), _anchor())
    assert not anchor_matches(
        _chunk("customers were 16%, 15%, and 13%", acc="0000320193-26-000026"), _anchor()
    )


def test_match_ignores_whitespace_and_case() -> None:
    assert anchor_matches(_chunk("customers were 16%,\n 15%,   AND 13%"), _anchor())


def test_match_ignores_section_label() -> None:
    assert anchor_matches(_chunk("x 16%, 15%, and 13% y", section="Properties"), _anchor())


def test_first_hit_rank_and_miss() -> None:
    chunks = [_chunk("noise"), _chunk("more noise"), _chunk("16%, 15%, and 13%")]
    assert first_hit_rank(chunks, [_anchor()]) == 3
    assert first_hit_rank(chunks[:2], [_anchor()]) is None


def test_first_hit_rank_any_anchor() -> None:
    chunks = [_chunk("alpha beta gamma"), _chunk("delta epsilon zeta")]
    anchors = [_anchor("never present text"), _anchor("delta epsilon")]
    assert first_hit_rank(chunks, anchors) == 2


def test_anchors_covered_respects_k() -> None:
    chunks = [_chunk("first anchor text"), _chunk("filler"), _chunk("second anchor text")]
    anchors = [_anchor("first anchor text"), _anchor("second anchor text")]
    assert anchors_covered(chunks, anchors, k=1) == (1, 2)
    assert anchors_covered(chunks, anchors, k=3) == (2, 2)


def test_section_agrees_diagnostic() -> None:
    hit = [_chunk("16%, 15%, and 13%", section="Properties")]
    assert section_agrees(hit, [_anchor(section="Business")]) is False
    assert section_agrees(hit, [_anchor(section="Properties")]) is True
    assert section_agrees([_chunk("noise")], [_anchor()]) is None


def test_summarize_hit_at_k_and_mrr() -> None:
    s = summarize([1, 3, None, 8])
    assert s["hit@1"] == 0.25
    assert s["hit@3"] == 0.5
    assert s["hit@8"] == 0.75
    assert abs(s["mrr"] - (1 + 1 / 3 + 1 / 8) / 4) < 1e-9
    assert summarize([]) == {}
