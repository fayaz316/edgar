"""Is the judge fit to use? Apply the protocol's calibration guard to judge results on claims_v1 (pure, tested)."""

from __future__ import annotations

from typing import Any

# (kind(s), minimum caught, out of) — written in PROTOCOL.md before the judge was run
REQUIREMENTS: list[tuple[tuple[str, ...], int, int]] = [
    (("extrapolation",), 3, 4),
    (("direction",), 2, 3),
    (("wrong_passage",), 2, 3),
    (("number", "entity"), 7, 8),
]
MAX_FALSE_FLAGS = 1  # of the 18 faithful claims
MIN_DETECTED = 15  # of the 18 unfaithful claims


def evaluate(rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """rows: {kind, label, verdict}. Returns (valid for use, the failed requirements)."""
    failures: list[str] = []
    faithful = [r for r in rows if r["kind"] == "faithful"]
    bad = [r for r in rows if r["kind"] != "faithful"]

    def caught(rs: list[dict[str, Any]]) -> int:
        return sum(1 for r in rs if r["verdict"] == "unsupported")

    flags = sum(1 for r in faithful if r["verdict"] == "unsupported")
    if flags > MAX_FALSE_FLAGS:
        failures.append(f"false flags on faithful claims: {flags} (max {MAX_FALSE_FLAGS})")
    if caught(bad) < MIN_DETECTED:
        failures.append(f"unfaithful claims caught: {caught(bad)}/{len(bad)} (min {MIN_DETECTED})")
    for kinds, need, total in REQUIREMENTS:
        group = [r for r in bad if r["kind"] in kinds]
        if len(group) != total:
            failures.append(f"{'+'.join(kinds)}: expected {total} items, found {len(group)}")
        elif caught(group) < need:
            failures.append(f"{'+'.join(kinds)}: caught {caught(group)}/{total} (min {need})")
    return not failures, failures
