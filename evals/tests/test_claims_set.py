"""The labeled claims set must stay well-formed: the protocol freezes it, so a malformed edit is a bug."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parents[1] / "claims"
KINDS = {"faithful", "number", "entity", "extrapolation", "direction", "wrong_passage"}


def _load() -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    passages = yaml.safe_load((HERE / "passages_v1.yaml").read_text())
    items = yaml.safe_load((HERE / "claims_v1.yaml").read_text())
    return passages, items


def test_every_item_references_a_real_passage_and_a_valid_kind() -> None:
    passages, items = _load()
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))
    for i in items:
        assert i["kind"] in KINDS
        assert i["label"] == ("supported" if i["kind"] == "faithful" else "unsupported")
        assert all(k in passages for k in i["evidence"])  # type: ignore[attr-defined]
        assert "[1]" in str(i["claim"])


def test_balance_matches_the_protocol() -> None:
    _, items = _load()
    counts = Counter(str(i["kind"]) for i in items)
    assert counts["faithful"] == 18
    assert all(counts[k] >= 3 for k in KINDS - {"faithful"})  # protocol: each kind at least 3 items


def test_claim_check_l1_keeps_its_enforcement_contract() -> None:
    """Layer 1 of the eval gate (evals/GATE.md): the thresholds that let L1 enforce (ADR 0014) must still hold.
    Deterministic and offline: no model is loaded."""
    from services.agent.claims import check_answer

    passages, items = _load()
    flagged_faithful = 0
    faithful = number_total = number_caught = 0
    for it in items:
        evidence = [passages[k] for k in it["evidence"]]  # type: ignore[attr-defined]
        [check] = check_answer(str(it["claim"]), evidence)  # nli=None -> L1 only
        if it["kind"] == "faithful":
            faithful += 1
            flagged_faithful += int(check.l1_unsupported)
        if it["kind"] == "number":
            number_total += 1
            number_caught += int(check.l1_unsupported)
    assert flagged_faithful / faithful <= 0.10, (
        f"L1 false-flags {flagged_faithful}/{faithful} faithful claims"
    )
    assert number_caught / number_total >= 0.90, (
        f"L1 caught only {number_caught}/{number_total} changed numbers"
    )


def test_claims_v2_is_well_formed_and_balanced_as_specified() -> None:
    passages = yaml.safe_load((HERE / "passages_v2.yaml").read_text())
    items = yaml.safe_load((HERE / "claims_v2.yaml").read_text())
    counts = Counter(str(i["kind"]) for i in items)
    assert counts == {"meta_date": 6, "faithful": 4, "wrong_date": 4, "laundering": 3, "number": 3}
    for i in items:
        assert i["label"] == (
            "supported" if i["kind"] in {"meta_date", "faithful"} else "unsupported"
        )
        assert all(k in passages for k in i["evidence"]) and i["metadata"]


def test_date_guard_passes_a_perfect_checker_and_fails_the_real_failure_shape() -> None:
    from evals.claims.run_dates import guard

    def rows(**flag: bool) -> list[dict[str, object]]:
        kinds = [("m03", "meta_date", "supported", False)] + [
            (f"w0{i}", "wrong_date", "unsupported", True) for i in range(4)
        ]
        kinds += [(f"l0{i}", "laundering", "unsupported", True) for i in range(3)] + [
            (f"c0{i}", "number", "unsupported", True) for i in range(3)
        ]
        return [{"id": i, "kind": k, "label": lab, "new": flag.get(i, v)} for i, k, lab, v in kinds]

    assert guard(rows()) == (True, [])
    ok, why = guard(rows(m03=True))
    assert not ok and any("m03" in w for w in why)
    ok, why = guard(rows(l00=False))
    assert not ok and any("laundering" in w for w in why)
