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
