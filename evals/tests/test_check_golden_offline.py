from __future__ import annotations

from evals.check_golden_offline import check_anchor
from evals.schema import EvidenceAnchor
from services.ingest.parse import Chunk

ACC = "0001045810-26-000075"


def _a(section: str, hint: str = "16%, 15%, and 13%") -> EvidenceAnchor:
    return EvidenceAnchor(accession=ACC, section=section, snippet_hint=hint)


def test_ok_when_snippet_under_anchored_section() -> None:
    chunks = [Chunk("Financial Statements", 0, "customers were 16%,  15%, and 13% of revenue")]
    assert check_anchor(chunks, _a("Financial Statements")) == ("OK", ["Financial Statements"])


def test_wrong_section_lists_where_it_was_found() -> None:
    chunks = [Chunk("Financial Statements", 0, "customers were 16%, 15%, and 13% of revenue")]
    assert check_anchor(chunks, _a("Business")) == ("WRONG_SECTION", ["Financial Statements"])


def test_not_found_when_snippet_missing_or_split_across_chunks() -> None:
    chunks = [Chunk("MD&A", 0, "customers were 16%, 15%,"), Chunk("MD&A", 1, "and 13% of revenue")]
    assert check_anchor(chunks, _a("MD&A")) == ("NOT_FOUND", [])
