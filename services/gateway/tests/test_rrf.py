"""RRF fusion unit tests — pure function, no DB/network (CI-safe)."""

from __future__ import annotations

from services.gateway.retrieval import rrf_fuse


def test_both_legs_agree_first() -> None:
    fused = rrf_fuse([10, 11, 12], [10, 13, 11])
    top = max(fused.items(), key=lambda kv: kv[1][0])
    assert top[0] == 10  # rank1 + rank1
    assert top[1][1] == 1 and top[1][2] == 1


def test_scores_are_reciprocal_rank_sums() -> None:
    fused = rrf_fuse([7], [7])
    expected = 1 / (60 + 1) + 1 / (60 + 1)
    assert abs(fused[7][0] - expected) < 1e-12


def test_missing_from_one_leg_still_ranks() -> None:
    fused = rrf_fuse([4, 5], [])
    assert fused[4][0] > fused[5][0] > 0
    assert fused[4][2] is None  # absent from semantic leg


def test_disjoint_lists_interleave_by_rank() -> None:
    fused = rrf_fuse([1, 2], [3, 4])
    scores = {cid: v[0] for cid, v in fused.items()}
    assert abs(scores[1] - scores[3]) < 1e-12  # same rank position, same score
    assert scores[1] > scores[2] and scores[3] > scores[4]


def test_provenance_ranks_recorded() -> None:
    fused = rrf_fuse([9, 8], [8])
    assert fused[8][1] == 2 and fused[8][2] == 1
    assert fused[9][2] is None


def test_deterministic_ordering_under_ties() -> None:
    a = rrf_fuse([1, 2, 3], [3, 2, 1])
    b = rrf_fuse([1, 2, 3], [3, 2, 1])
    assert [k for k, _ in sorted(a.items(), key=lambda kv: (-kv[1][0], kv[0]))] == [
        k for k, _ in sorted(b.items(), key=lambda kv: (-kv[1][0], kv[0]))
    ]
