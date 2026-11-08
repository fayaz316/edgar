from evals.finetune.exclusion import (
    Chunk,
    exclusion_set,
    jaccard,
    near_duplicate_ids,
    neighbour_ids,
    shingles,
    skipped_ids_from_header,
)
from evals.schema import EvidenceAnchor

TEXT = "the company faces intense competition from many rivals in every market it serves today"


def c(i: int, text: str, doc: int = 1, seq: int = 0, acc: str = "0000000000-00-000001") -> Chunk:
    return Chunk(i, doc, acc, "Risk Factors", seq, text)


def test_jaccard_identical_and_disjoint() -> None:
    assert jaccard(shingles(TEXT), shingles(TEXT)) == 1.0
    assert (
        jaccard(shingles(TEXT), shingles("completely different words here for the second one now"))
        == 0.0
    )


def test_skipped_ids_parsed_from_header() -> None:
    hdr = "#   9037  AAPL 10-Q   boilerplate (x)\n#   7537  JPM  10-K   boilerplate\n# Everything else 17"
    assert skipped_ids_from_header(hdr) == {9037, 7537}


def test_neighbours_are_same_doc_section_adjacent_seq() -> None:
    chunks = [c(1, "a", seq=0), c(2, "b", seq=1), c(3, "c", seq=2), c(4, "d", doc=2, seq=1)]
    assert neighbour_ids(chunks, {2}) == {1, 3}


def test_near_duplicate_found_across_documents() -> None:
    chunks = [
        c(1, TEXT),
        c(2, TEXT + " and more", doc=2),
        c(3, "unrelated text about banking deposits and loans in the quarter"),
    ]
    assert near_duplicate_ids(chunks, {1}) == {2}


def test_exclusion_set_combines_evidence_neighbours_and_dups() -> None:
    chunks = [
        c(1, "filler one", seq=0),
        c(2, TEXT, seq=1),
        c(3, "filler three", seq=2),
        c(4, TEXT, doc=2, seq=5, acc="0000000000-00-000002"),
        c(5, "far away unrelated passage on something else entirely different", doc=3),
    ]
    anchors = [
        EvidenceAnchor(
            accession="0000000000-00-000001",
            section="Risk Factors",
            snippet_hint="intense competition from many rivals",
        )
    ]
    assert exclusion_set(chunks, anchors, set()) == {1, 2, 3, 4}
