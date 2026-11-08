"""Apply the pre-registered adoption rule (evals/finetune/PROTOCOL.md) to two result directories.

  python -m evals.finetune.decide --control DIR --candidate DIR [--out FILE]
  exit 0 = ADOPT, 1 = REJECT, 2 = not comparable

Each directory holds run_retrieval outputs named golden_v0.json, heldout_v1.json, heldout_v2.json, heldout_v3.json and
heldout_v4.json. The rule is applied by this script, not by hand, so it cannot be bent after seeing numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.gate import GateReport, build, compare, hits, mrr

V4 = "heldout_v4"
V4_MRR_GAIN = 0.05
V4_HIT8_GAIN = 3
MAX_TOTAL_NEGATIVE_FLIPS = 5


@dataclass
class Decision:
    verdict: str  # ADOPT | REJECT | ERROR
    reasons: list[str]
    detail: dict[str, Any]


def _v4_ranks(path: Path) -> dict[str, int | None]:
    run = json.loads(path.read_text())
    return {r["id"]: r["rank"] for r in run["rows"]}


def decide(
    control: dict[str, Any],
    candidate: dict[str, Any],
    v4_c: dict[str, int | None],
    v4_k: dict[str, int | None],
    k: int = 8,
) -> Decision:
    """control/candidate: gate documents for v0..v3 (embedders intentionally differ). v4_c / v4_k: id -> rank for
    control / candidate."""
    if control["embedder"] == candidate["embedder"]:
        return Decision("ERROR", ["candidate and control used the same embedder"], {})
    if set(v4_c) != set(v4_k):
        return Decision("ERROR", ["v4 question ids differ between control and candidate"], {})
    # gate.compare refuses different embedders by design; here the difference is the experiment, so align the label
    # AFTER asserting it differs. Corpus fingerprint, config, k and golden hashes are still compared strictly.
    aligned = dict(candidate, embedder=control["embedder"])
    report: GateReport = compare(control, aligned)
    if report.verdict == "ERROR":
        return Decision("ERROR", report.reasons, {})

    ids = sorted(v4_c)
    rc, rk = [v4_c[i] for i in ids], [v4_k[i] for i in ids]
    d_mrr, d_hit = mrr(rk) - mrr(rc), hits(rk, k) - hits(rc, k)
    v4_lost = [i for i in ids if (v4_c[i] or 99) <= k and not ((v4_k[i] or 99) <= k)]
    v4_gained = [i for i in ids if (v4_k[i] or 99) <= k and not ((v4_c[i] or 99) <= k)]
    old_lost = sum(len(s.negative_flips) for s in report.sets)
    total_lost = old_lost + len(v4_lost)

    reasons: list[str] = []
    if d_mrr < V4_MRR_GAIN:
        reasons.append(f"v4 MRR gain {d_mrr:+.3f} < required {V4_MRR_GAIN}")
    if d_hit < V4_HIT8_GAIN:
        reasons.append(f"v4 hit@{k} gain {d_hit:+d} < required {V4_HIT8_GAIN}")
    if report.verdict != "PASS":
        reasons += [f"regression on v0..v3: {r}" for r in report.reasons]
    if total_lost > MAX_TOTAL_NEGATIVE_FLIPS:
        reasons.append(
            f"{total_lost} negative flips across v0..v4 (limit {MAX_TOTAL_NEGATIVE_FLIPS})"
        )
    detail = {
        "v4": {
            "n": len(ids),
            "hit8": [hits(rc, k), hits(rk, k)],
            "mrr": [round(mrr(rc), 4), round(mrr(rk), 4)],
            "lost": v4_lost,
            "gained": v4_gained,
        },
        "v0_v3": {
            "combined_hit8": list(report.combined_hit8),
            "combined_mrr": [round(x, 4) for x in report.combined_mrr],
            "sets": [
                {
                    "name": s.name,
                    "n": s.n,
                    "hit8": [s.hit8_before, s.hit8_after],
                    "mrr": [round(s.mrr_before, 4), round(s.mrr_after, 4)],
                    "lost": s.negative_flips,
                    "gained": s.positive_flips,
                }
                for s in report.sets
            ],
        },
        "total_negative_flips": total_lost,
    }
    return Decision("REJECT" if reasons else "ADOPT", reasons, detail)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    c_dir, k_dir = Path(args.control), Path(args.candidate)
    control, candidate = build(c_dir), build(k_dir)
    dec = decide(
        control,
        candidate,
        _v4_ranks(c_dir / f"{V4}.json"),
        _v4_ranks(k_dir / f"{V4}.json"),
        control["k"],
    )
    text = json.dumps({"verdict": dec.verdict, "reasons": dec.reasons, **dec.detail}, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text)
    return {"ADOPT": 0, "REJECT": 1, "ERROR": 2}[dec.verdict]


if __name__ == "__main__":
    sys.exit(main())
