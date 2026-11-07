from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals import freeze
from evals.gate import DEFAULT_CONFIG, Thresholds, compare, render


def _doc(sets: Mapping[str, Mapping[str, int | None]], **over: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "k": 8,
        "embedder": "bge",
        "corpus_fingerprint": "abc",
        "golden_sha256": {n: "h" for n in sets},
        "config": dict(DEFAULT_CONFIG),
        "sets": {n: dict(v) for n, v in sets.items()},
    }
    doc.update(over)
    return doc


def _set(n: int, rank: int | None = 2, prefix: str = "q") -> dict[str, int | None]:
    return {f"{prefix}{i}": rank for i in range(n)}


# realistic sizes: one lost question in ~30 moves MRR by about 0.017, like in the real 78-question run
BASE = {"a": _set(20), "b": _set(10, 3, "r")}


def test_identical_run_passes() -> None:
    assert compare(_doc(BASE), _doc(BASE)).verdict == "PASS"


def test_improvements_never_fail_and_are_reported_as_gained() -> None:
    before = {"a": {**_set(19), "q19": None}, "b": BASE["b"]}
    after = {"a": {**_set(19, 1), "q19": 5}, "b": BASE["b"]}
    r = compare(_doc(before), _doc(after))
    assert r.verdict == "PASS" and r.sets[0].positive_flips == ["q19"]


def test_one_lost_question_is_a_reported_negative_flip_but_tolerated() -> None:
    worse = {"a": {**_set(19), "q19": None}, "b": BASE["b"]}
    r = compare(_doc(BASE), _doc(worse))
    assert r.sets[0].negative_flips == ["q19"] and r.verdict == "PASS"


def test_two_lost_questions_exceed_the_combined_hit_limit() -> None:
    worse = {"a": {**_set(18), "q18": None, "q19": None}, "b": BASE["b"]}
    r = compare(_doc(BASE), _doc(worse))
    assert r.verdict == "FAIL" and any("combined hit@8" in x for x in r.reasons)


def test_mrr_drop_fails_even_when_every_question_still_hits() -> None:
    r = compare(_doc(BASE), _doc({"a": _set(20, 6), "b": _set(10, 7, "r")}))
    assert r.verdict == "FAIL" and any("MRR" in x for x in r.reasons)
    assert all(
        not d.negative_flips for d in r.sets
    )  # a pure ranking regression, invisible to hit@k


def test_a_single_set_collapsing_fails_on_its_own() -> None:
    worse = {"a": {**_set(17), "q17": None, "q18": None, "q19": None}, "b": BASE["b"]}
    r = compare(_doc(BASE), _doc(worse))
    assert r.verdict == "FAIL" and any(x.startswith("a: hit@8") for x in r.reasons)


def test_too_many_negative_flips_fail() -> None:
    relaxed = Thresholds(
        combined_hit8_drop=99, set_hit8_drop=99, combined_mrr_drop=9, set_mrr_drop=9
    )
    worse = {"a": {**_set(15), **{f"q{i}": None for i in range(15, 20)}}, "b": BASE["b"]}
    r = compare(_doc(BASE), _doc(worse), relaxed)
    assert r.verdict == "FAIL" and any("negative flips" in x for x in r.reasons)


def test_different_corpus_embedder_or_golden_files_are_errors_not_passes() -> None:
    for over in (
        {"corpus_fingerprint": "zzz"},
        {"embedder": "other"},
        {"golden_sha256": {"a": "x", "b": "h"}},
    ):
        assert compare(_doc(BASE), _doc(BASE, **over)).verdict == "ERROR"


def test_candidate_must_use_product_defaults() -> None:
    r = compare(
        _doc(BASE), _doc(BASE, config={"lexical": "all", "rerank": False, "filing_hints": True})
    )
    assert r.verdict == "ERROR" and "product defaults" in r.reasons[0]


def test_render_names_the_lost_questions() -> None:
    worse = {"a": {**_set(19), "q19": None}, "b": BASE["b"]}
    text = render(compare(_doc(BASE), _doc(worse)))
    assert "lost: q19" in text and "GATE: PASS" in text


def test_frozen_evaluation_files_match_the_manifest() -> None:
    """If this fails, a frozen set was edited. Either revert it, or run `python -m evals.freeze --update`
    AND add a DECISION_LOG entry explaining why the frozen data legitimately changed."""
    assert Path(freeze.MANIFEST).exists(), "run: python -m evals.freeze --update"
    assert freeze.mismatches() == []
    assert set(json.loads(freeze.MANIFEST.read_text())) == set(freeze.FROZEN)


def test_a_baseline_built_with_weaker_settings_is_an_error_not_a_free_pass() -> None:
    weak = {"lexical": "all", "rerank": False, "filing_hints": True}
    r = compare(_doc(BASE, config=weak), _doc(BASE))
    assert (
        r.verdict == "ERROR" and "baseline was not built with the product defaults" in r.reasons[0]
    )
