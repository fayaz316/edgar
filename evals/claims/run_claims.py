"""Run the claim checker over claims_v1.yaml ONCE and apply the protocol's guard.

uv run --group local-embed python -m evals.claims.run_claims
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from services.agent.claims import CrossEncoderNli, check_answer

HERE = Path(__file__).parent


def main() -> int:
    passages = yaml.safe_load((HERE / "passages_v1.yaml").read_text())
    items = yaml.safe_load((HERE / "claims_v1.yaml").read_text())
    nli = CrossEncoderNli()
    rows: list[dict[str, Any]] = []
    for it in items:
        evidence = [passages[k] for k in it["evidence"]]
        [check] = check_answer(it["claim"], evidence, nli)
        rows.append(
            {
                "id": it["id"],
                "kind": it["kind"],
                "label": it["label"],
                "l1": check.l1_unsupported,
                "l2": check.l2_unsupported,
                "combined": check.unsupported,
                "entailment": round(check.entailment or 0.0, 3),
                "missing_numbers": check.missing_numbers,
                "missing_companies": check.missing_companies,
            }
        )

    faithful = [r for r in rows if r["kind"] == "faithful"]
    bad = [r for r in rows if r["kind"] != "faithful"]
    kinds = sorted({r["kind"] for r in bad})
    print(
        f"{'layer':<10} {'false-flag on faithful':<26} "
        + " ".join(f"{k[:7]:>8}" for k in kinds)
        + "   overall"
    )
    summary: dict[str, Any] = {}
    for layer in ("l1", "l2", "combined"):
        ff = sum(r[layer] for r in faithful)
        per_kind: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
        for r in bad:
            per_kind[r["kind"]][1] += 1
            per_kind[r["kind"]][0] += int(r[layer])
        det = sum(v[0] for v in per_kind.values())
        print(
            f"{layer:<10} {ff}/{len(faithful)} ({ff / len(faithful):.0%})".ljust(38)
            + " ".join(f"{per_kind[k][0]}/{per_kind[k][1]:>2}".rjust(8) for k in kinds)
            + f"   {det}/{len(bad)} ({det / len(bad):.0%})"
        )
        summary[layer] = {
            "false_flag": ff / len(faithful),
            "detect": det / len(bad),
            "per_kind": {k: v[0] / v[1] for k, v in per_kind.items()},
        }
    print(
        "\nfaithful claims the combined checker flagged:",
        [
            (r["id"], r["missing_numbers"], r["missing_companies"], r["entailment"])
            for r in faithful
            if r["combined"]
        ],
    )
    print(
        "unfaithful claims it missed:",
        [(r["id"], r["kind"], r["entailment"]) for r in bad if not r["combined"]],
    )

    c, l1 = summary["combined"], summary["l1"]
    enforce_combined = (
        c["false_flag"] <= 0.20 and c["detect"] >= 0.60 and c["per_kind"].get("number", 0) >= 0.90
    )
    enforce_l1 = l1["false_flag"] <= 0.10 and l1["per_kind"].get("number", 0) >= 0.90
    mode = (
        "enforce combined (L1+L2)"
        if enforce_combined
        else "enforce L1 only"
        if enforce_l1
        else "REPORT-ONLY"
    )
    print(f"\nGUARD => {mode}")
    (HERE / "results_run1.json").write_text(
        json.dumps({"rows": rows, "summary": summary, "mode": mode}, indent=1)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
