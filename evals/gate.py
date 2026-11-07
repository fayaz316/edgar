"""Retrieval regression gate: compare a candidate run with a committed baseline (rules: evals/GATE.md).

  python -m evals.gate build  --results-dir DIR --out FILE     # results of run_retrieval -> baseline/candidate file
  python -m evals.gate compare --baseline FILE --candidate FILE  # exit 0 pass, 1 regression, 2 not comparable

Pure logic + a small CLI; no database or model needed to compare two files.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SETS = ("golden_v0", "heldout_v1", "heldout_v2", "heldout_v3")
# The product default the gate protects. Changing a default (for example adopting a reranker) must change this
# line, regenerate the baseline, and come with an ADR: see evals/GATE.md.
DEFAULT_CONFIG = {"lexical": "bm25", "rerank": False, "filing_hints": True}


@dataclass(frozen=True)
class Thresholds:
    combined_mrr_drop: float = 0.02
    combined_hit8_drop: int = 1
    set_hit8_drop: int = 2
    set_mrr_drop: float = 0.05
    max_negative_flips: int = 4


@dataclass
class SetDelta:
    name: str
    n: int
    hit8_before: int
    hit8_after: int
    mrr_before: float
    mrr_after: float
    negative_flips: list[str] = field(default_factory=list)  # hit before, miss now
    positive_flips: list[str] = field(default_factory=list)  # miss before, hit now


@dataclass
class GateReport:
    verdict: Literal["PASS", "FAIL", "ERROR"]
    reasons: list[str]
    sets: list[SetDelta]
    combined_mrr: tuple[float, float] = (0.0, 0.0)
    combined_hit8: tuple[int, int] = (0, 0)


def mrr(ranks: list[int | None]) -> float:
    return sum(1 / r for r in ranks if r) / len(ranks) if ranks else 0.0


def hits(ranks: list[int | None], k: int) -> int:
    return sum(1 for r in ranks if r is not None and r <= k)


def build(results_dir: Path, *, golden_dir: Path = Path("evals/golden")) -> dict[str, Any]:
    """Collapse the run_retrieval outputs for every set into one comparable document."""
    from evals.freeze import sha256_file

    golden_files = {
        "golden_v0": "golden_v0.yaml",
        "heldout_v1": "golden_v1_heldout.yaml",
        "heldout_v2": "golden_v2_heldout.yaml",
        "heldout_v3": "golden_v3_heldout.yaml",
    }
    doc: dict[str, Any] = {"sets": {}, "golden_sha256": {}}
    for name in SETS:
        run = json.loads((results_dir / f"{name}.json").read_text())
        doc.setdefault("k", run["k"])
        doc.setdefault("embedder", run["embedder"])
        doc.setdefault("corpus_fingerprint", run.get("corpus_fingerprint"))
        doc.setdefault("config", run.get("config"))
        if (run["k"], run["embedder"], run.get("corpus_fingerprint"), run.get("config")) != (
            doc["k"],
            doc["embedder"],
            doc["corpus_fingerprint"],
            doc["config"],
        ):
            raise SystemExit(f"{name}: run settings differ from the other sets")
        doc["sets"][name] = {r["id"]: r["rank"] for r in run["rows"]}
        doc["golden_sha256"][name] = sha256_file(golden_dir / golden_files[name])
    return doc


def compare(
    baseline: dict[str, Any], candidate: dict[str, Any], th: Thresholds | None = None
) -> GateReport:
    th = th or Thresholds()
    problems: list[str] = []
    for key in ("k", "embedder", "corpus_fingerprint", "golden_sha256"):
        if baseline.get(key) != candidate.get(key):
            problems.append(f"{key} differs from the baseline (not comparable)")
    if candidate.get("config") != DEFAULT_CONFIG:
        problems.append(
            f"candidate was not run with the product defaults: {candidate.get('config')}"
        )
    if baseline.get("corpus_fingerprint") is None:
        problems.append("baseline has no corpus fingerprint; regenerate it")
    if set(baseline["sets"]) != set(candidate["sets"]):
        problems.append("question sets differ between baseline and candidate")
    if problems:
        return GateReport("ERROR", problems, [])

    k = baseline["k"]
    deltas: list[SetDelta] = []
    reasons: list[str] = []
    tot_b: list[int | None] = []
    tot_c: list[int | None] = []
    for name in sorted(baseline["sets"]):
        b, c = baseline["sets"][name], candidate["sets"][name]
        if set(b) != set(c):
            return GateReport("ERROR", [f"{name}: question ids differ from the baseline"], [])
        ids = sorted(b)
        rb, rc = [b[i] for i in ids], [c[i] for i in ids]
        tot_b += rb
        tot_c += rc
        d = SetDelta(name, len(ids), hits(rb, k), hits(rc, k), mrr(rb), mrr(rc))
        for i in ids:
            was, now = b[i] is not None and b[i] <= k, c[i] is not None and c[i] <= k
            if was and not now:
                d.negative_flips.append(i)
            if now and not was:
                d.positive_flips.append(i)
        deltas.append(d)
        if d.hit8_before - d.hit8_after > th.set_hit8_drop:
            reasons.append(
                f"{name}: hit@{k} fell {d.hit8_before} -> {d.hit8_after} (limit {th.set_hit8_drop})"
            )
        if d.mrr_before - d.mrr_after > th.set_mrr_drop:
            reasons.append(
                f"{name}: MRR fell {d.mrr_before:.3f} -> {d.mrr_after:.3f} (limit {th.set_mrr_drop})"
            )

    cm, cm2 = mrr(tot_b), mrr(tot_c)
    ch, ch2 = hits(tot_b, k), hits(tot_c, k)
    if cm - cm2 > th.combined_mrr_drop:
        reasons.append(f"combined MRR fell {cm:.3f} -> {cm2:.3f} (limit {th.combined_mrr_drop})")
    if ch - ch2 > th.combined_hit8_drop:
        reasons.append(f"combined hit@{k} fell {ch} -> {ch2} (limit {th.combined_hit8_drop})")
    flips = sum(len(d.negative_flips) for d in deltas)
    if flips > th.max_negative_flips:
        reasons.append(f"{flips} negative flips (limit {th.max_negative_flips})")
    return GateReport("FAIL" if reasons else "PASS", reasons, deltas, (cm, cm2), (ch, ch2))


def render(report: GateReport) -> str:
    out = [f"GATE: {report.verdict}"]
    out += [f"  - {r}" for r in report.reasons]
    if report.sets:
        out.append(f"  {'set':<11}{'n':>3}  {'hit@8':>9}  {'MRR':>15}  flips (lost / gained)")
        for d in report.sets:
            out.append(
                f"  {d.name:<11}{d.n:>3}  {d.hit8_before:>3} -> {d.hit8_after:<3}"
                f"  {d.mrr_before:.3f} -> {d.mrr_after:.3f}  {len(d.negative_flips)} / {len(d.positive_flips)}"
            )
            if d.negative_flips:
                out.append(f"      lost: {', '.join(d.negative_flips)}")
        out.append(
            f"  combined: hit@8 {report.combined_hit8[0]} -> {report.combined_hit8[1]}, "
            f"MRR {report.combined_mrr[0]:.3f} -> {report.combined_mrr[1]:.3f}"
        )
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--results-dir", required=True)
    b.add_argument("--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("--baseline", required=True)
    c.add_argument("--candidate", required=True)
    args = ap.parse_args()
    if args.cmd == "build":
        Path(args.out).write_text(
            json.dumps(build(Path(args.results_dir)), indent=1, sort_keys=True)
        )
        print(f"wrote {args.out}")
        return 0
    report = compare(
        json.loads(Path(args.baseline).read_text()), json.loads(Path(args.candidate).read_text())
    )
    print(render(report))
    return {"PASS": 0, "FAIL": 1, "ERROR": 2}[report.verdict]


if __name__ == "__main__":
    sys.exit(main())
