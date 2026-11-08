from typing import Any

from evals.finetune.decide import decide
from evals.gate import DEFAULT_CONFIG


def doc(embedder: str, ranks: dict[str, dict[str, int | None]]) -> dict[str, Any]:
    return {
        "k": 8,
        "embedder": embedder,
        "corpus_fingerprint": "fp",
        "config": DEFAULT_CONFIG,
        "golden_sha256": {n: "h" for n in ranks},
        "sets": ranks,
    }


OLD: dict[str, dict[str, int | None]] = {"golden_v0": {f"q{i}": (i % 8) + 1 for i in range(10)}}
V4_BASE: dict[str, int | None] = {
    f"v{i}": (None if i < 6 else 2) for i in range(10)
}  # 6 misses, 4 hits
V4_BETTER: dict[str, int | None] = {
    f"v{i}": (1 if i < 4 else (None if i < 6 else 2)) for i in range(10)
}  # 4 gained, rank 1


def test_adopt_when_every_condition_holds() -> None:
    d = decide(doc("base", OLD), doc("ft", OLD), V4_BASE, V4_BETTER)
    assert d.verdict == "ADOPT", d.reasons


def test_reject_when_v4_gain_too_small() -> None:
    barely: dict[str, int | None] = {**V4_BASE, "v0": 1}
    d = decide(doc("base", OLD), doc("ft", OLD), V4_BASE, barely)
    assert d.verdict == "REJECT"
    assert any("hit@8 gain" in r for r in d.reasons)


def test_reject_on_regression_in_old_sets() -> None:
    worse: dict[str, dict[str, int | None]] = {
        "golden_v0": {
            k: (None if i < 4 else v) for i, (k, v) in enumerate(OLD["golden_v0"].items())
        }
    }
    d = decide(doc("base", OLD), doc("ft", worse), V4_BASE, V4_BETTER)
    assert d.verdict == "REJECT"
    assert any("regression" in r for r in d.reasons)


def test_error_when_same_embedder_or_different_corpus() -> None:
    assert decide(doc("same", OLD), doc("same", OLD), V4_BASE, V4_BETTER).verdict == "ERROR"
    other = doc("ft", OLD)
    other["corpus_fingerprint"] = "different"
    assert decide(doc("base", OLD), other, V4_BASE, V4_BETTER).verdict == "ERROR"
