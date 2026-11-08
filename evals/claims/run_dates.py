"""Run the date-aware L1 on claims_v2 ONCE and apply the guard in L1_DATES.md. Offline: no model, no database.

uv run python -m evals.claims.run_dates
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from services.agent.claims import check_answer, numbers_in, passage_numbers

HERE = Path(__file__).parent


def guard(rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """The pre-registered adoption guard (L1_DATES.md), applied to the NEW checker's flags."""
    failures: list[str] = []
    faithful = [r for r in rows if r["label"] == "supported"]
    flags = [r["id"] for r in faithful if r["new"]]
    if len(flags) > 1:
        failures.append(f"false flags on faithful claims: {flags} (max 1)")
    if any(r["id"] == "m03" and r["new"] for r in rows):
        failures.append(
            "the real-failure shape (m03: a date that exists only in metadata) is still flagged"
        )

    def caught(kind: str) -> tuple[int, int]:
        group = [r for r in rows if r["kind"] == kind]
        return sum(1 for r in group if r["new"]), len(group)

    for kind, need in (("wrong_date", 3), ("laundering", 3), ("number", 3)):
        got, total = caught(kind)
        if got < need:
            failures.append(f"{kind}: caught {got}/{total} (min {need})")
    return not failures, failures


def main() -> int:
    passages = yaml.safe_load((HERE / "passages_v2.yaml").read_text())
    items = yaml.safe_load((HERE / "claims_v2.yaml").read_text())
    rows: list[dict[str, Any]] = []
    for it in items:
        ev = [passages[k] for k in it["evidence"]]
        [new] = check_answer(it["claim"], ev, metadata_dates=it["metadata"])
        legacy = bool(numbers_in(new.text) - set().union(*(passage_numbers(p["text"]) for p in ev)))
        rows.append(
            {
                "id": it["id"],
                "kind": it["kind"],
                "label": it["label"],
                "new": new.l1_unsupported,
                "old": legacy,
                "missing_dates": new.missing_dates,
                "missing_numbers": new.missing_numbers,
            }
        )
    print(f"{'id':<5} {'kind':<11} {'label':<11} old-L1  new-L1  detail")
    for r in rows:
        mark = "" if (r["new"] == (r["label"] == "unsupported")) else "  <-- wrong"
        print(
            f"{r['id']:<5} {r['kind']:<11} {r['label']:<11} {'flag' if r['old'] else 'ok':<7} {'flag' if r['new'] else 'ok':<7} "
            f"{r['missing_dates'] or ''}{r['missing_numbers'] or ''}{mark}"
        )
    ok, failures = guard(rows)
    for tag in ("old", "new"):
        ff = sum(1 for r in rows if r["label"] == "supported" and r[tag])
        det = sum(1 for r in rows if r["label"] == "unsupported" and r[tag])
        print(f"{tag}-L1: false flags {ff}/10, unfaithful caught {det}/10")
    print("\nGUARD => " + ("ADOPT" if ok else "NOT ADOPTED: " + "; ".join(failures)))
    (HERE / "results_dates_run1.json").write_text(
        json.dumps({"adopt": ok, "failures": failures, "rows": rows}, indent=1)
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
