"""Calibrate the judge ONCE on claims_v1 and apply the protocol's guard.

uv run python -m evals.judge.calibrate        # needs GEMINI_API_KEY; 36 judge calls
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import yaml
from dotenv import load_dotenv

from evals.judge.calibration import evaluate
from evals.judge.judge import JUDGE_MODEL, DailyQuotaExhausted, GenaiJudgeModel, judge_claim

HERE = Path(__file__).parent
CLAIMS = HERE.parent / "claims"


def main() -> int:
    load_dotenv(".env")
    passages = yaml.safe_load((CLAIMS / "passages_v1.yaml").read_text())
    items = yaml.safe_load((CLAIMS / "claims_v1.yaml").read_text())
    model = GenaiJudgeModel(os.environ["GEMINI_API_KEY"])
    store = (
        HERE / f"calibration_{JUDGE_MODEL}.jsonl"
    )  # each verdict is saved as it arrives; a rerun resumes
    rows = [json.loads(line) for line in store.read_text().splitlines()] if store.exists() else []
    done = {r["id"] for r in rows}
    for it in items:
        if it["id"] in done:
            continue
        claim = str(it["claim"]).replace("[1]", "").replace(" .", ".").strip()
        try:
            j = judge_claim(claim, [passages[k] for k in it["evidence"]], model)
        except DailyQuotaExhausted as exc:
            print(
                f"STOPPED: daily quota used up after {len(rows)}/{len(items)} claims; rerun later to resume.\n{exc}"
            )
            return 3
        rows.append(
            {
                "id": it["id"],
                "kind": it["kind"],
                "label": it["label"],
                "verdict": j.verdict,
                "invalid": j.invalid,
                "reason": j.reason,
            }
        )
        with store.open("a") as f:
            f.write(json.dumps(rows[-1]) + "\n")
        agree = "ok " if j.verdict == it["label"] else "MISS"
        print(
            f"{agree} {it['id']:<5} {it['kind']:<14} mine={it['label']:<11} judge={j.verdict:<11} {j.reason[:70]}"
        )
    valid, failures = evaluate(rows)
    by: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        by[r["kind"]][1] += 1
        by[r["kind"]][0] += int(r["verdict"] == r["label"])
    print(
        "\nagreement with my labels, by kind:", {k: f"{a}/{b}" for k, (a, b) in sorted(by.items())}
    )
    print(
        f"invalid replies: {sum(r['invalid'] for r in rows)}   judge calls: {model.calls}   model: {JUDGE_MODEL}"
    )
    print("\nJUDGE " + ("VALID FOR USE" if valid else "NOT VALID: " + "; ".join(failures)))
    (HERE / "calibration_run1.json").write_text(
        json.dumps(
            {"model": JUDGE_MODEL, "valid": valid, "failures": failures, "rows": rows}, indent=1
        )
    )
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
