from __future__ import annotations

import math

from services.gateway.bm25 import bm25_rank, bm25_scores, idf


def test_idf_is_positive_and_falls_as_terms_get_common() -> None:
    assert idf(1000, 1) > idf(1000, 100) > idf(1000, 999) > 0


def test_rare_term_outweighs_common_term() -> None:
    # chunk 1 matches only the common word, chunk 2 only the rare one; same tf and length
    rows = [(1, "common", 1, 50), (2, "rare", 1, 50)]
    assert bm25_rank(rows, {"common": 900, "rare": 3}, 1000, 50.0) == [2, 1]


def test_covering_more_query_terms_beats_repeating_one() -> None:
    rows = [(1, "a", 1, 50), (1, "b", 1, 50), (2, "a", 4, 50)]
    assert bm25_rank(rows, {"a": 10, "b": 10}, 1000, 50.0)[0] == 1


def test_longer_chunk_scores_lower_for_the_same_match() -> None:
    rows = [(1, "t", 1, 200), (2, "t", 1, 20)]
    assert bm25_rank(rows, {"t": 5}, 1000, 60.0) == [2, 1]


def test_matches_a_hand_computed_score() -> None:
    # N=100, df=4: idf = ln(1 + 96.5/4.5) = ln(22.4444) = 3.11104
    # tf=2, dl=80, avgdl=40: norm = 2 + 1.2*(0.25 + 0.75*2) = 4.1
    # score = 3.11104 * 2 * 2.2 / 4.1 = 3.33868
    got = bm25_scores([(7, "t", 2, 80)], {"t": 4}, 100, 40.0)
    assert math.isclose(got[7], 3.33868, rel_tol=1e-4)


def test_ties_break_on_lower_id_and_empty_is_empty() -> None:
    rows = [(9, "t", 1, 50), (3, "t", 1, 50)]
    assert bm25_rank(rows, {"t": 5}, 1000, 50.0) == [3, 9]
    assert bm25_rank([], {}, 1000, 50.0) == []
