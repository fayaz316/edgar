"""Uncited-sentence evaluation (spec: UNCITED.md).

uv run python -m evals.claims.run_uncited a          # Evaluation A: the detector on labeled sentences (offline, once)
uv run --group local-embed python -m evals.claims.run_uncited b    # Evaluation B: real agent, rule OFF vs ON (resumable)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from services.agent.claims import needs_citation, uncited_substantive

HERE = Path(__file__).parent
B_STORE = HERE / "results_uncited_b.jsonl"


def guard_a(rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Pre-registered guard for Evaluation A (UNCITED.md)."""
    sub = [r for r in rows if r["label"] == "substantive"]
    struct = [r for r in rows if r["label"] == "structural"]
    missed = [r["id"] for r in sub if not r["flagged"]]
    over = [r["id"] for r in struct if r["flagged"]]
    failures = []
    if len(missed) > 3:
        failures.append(f"substantive sentences missed: {len(missed)}/{len(sub)} (max 3): {missed}")
    if len(over) > 1:
        failures.append(f"structural sentences flagged: {len(over)}/{len(struct)} (max 1): {over}")
    return not failures, failures


def run_a() -> int:
    items = yaml.safe_load((HERE / "uncited_labeled.yaml").read_text())
    rows = [
        {
            "id": i["id"],
            "source": i["source"],
            "label": i["label"],
            "flagged": needs_citation(i["text"]),
            "text": i["text"],
        }
        for i in items
    ]
    sub = [r for r in rows if r["label"] == "substantive"]
    struct = [r for r in rows if r["label"] == "structural"]
    print(
        f"substantive flagged: {sum(r['flagged'] for r in sub)}/{len(sub)}   structural flagged (wrongly): {sum(r['flagged'] for r in struct)}/{len(struct)}"
    )
    for r in rows:
        wrong = r["flagged"] != (r["label"] == "substantive")
        if wrong:
            print(f"  WRONG [{r['id']}] label={r['label']}: {r['text'][:90]}")
    ok, failures = guard_a(rows)
    print("\nEVALUATION A => " + ("PASS" if ok else "FAIL: " + "; ".join(failures)))
    (HERE / "results_uncited_a.json").write_text(
        json.dumps({"pass": ok, "failures": failures, "rows": rows}, indent=1)
    )
    return 0 if ok else 1


def guard_b(rows: list[dict[str, Any]], faithfulness: dict[str, float]) -> tuple[bool, list[str]]:
    """Pre-registered guard for Evaluation B. rows: {id, setting, loose, refused, infra}."""
    on = [r for r in rows if r["setting"] == "require"]
    off = [r for r in rows if r["setting"] == "off"]
    failures = []
    if any(r["infra"] for r in rows):
        failures.append("infrastructure errors in the counted runs (re-run them)")
    if sum(1 for r in on if r["loose"]) > 1:
        failures.append(
            f"with the rule ON, {sum(1 for r in on if r['loose'])}/{len(on)} answers still have an uncited substantive sentence (max 1)"
        )
    if sum(r["refused"] for r in on) > sum(r["refused"] for r in off) + 1:
        failures.append(
            f"refusals ON {sum(r['refused'] for r in on)} vs OFF {sum(r['refused'] for r in off)} (max +1)"
        )
    if faithfulness.get("require", 0.0) < faithfulness.get("off", 0.0) - 0.05:
        failures.append(
            f"judge faithfulness ON {faithfulness.get('require'):.3f} vs OFF {faithfulness.get('off'):.3f} (max drop 0.05)"
        )
    return not failures, failures


def run_b() -> int:
    load_dotenv(".env")
    from evals.judge.judge import DailyQuotaExhausted, GenaiJudgeModel, judge_answer
    from evals.judge.run_answers import evidence_from_citations, failed_for_infrastructure
    from services.agent.graph import run_agent
    from services.agent.llm import GeminiLLM
    from services.tools.bootstrap import registry_from_env

    questions = yaml.safe_load((HERE / "uncited_questions.yaml").read_text())
    registry = registry_from_env()
    llm = GeminiLLM(os.environ["GEMINI_API_KEY"])
    judge = GenaiJudgeModel(os.environ["GEMINI_API_KEY"])
    saved = (
        [json.loads(line) for line in B_STORE.read_text().splitlines()] if B_STORE.exists() else []
    )
    latest = {(r["id"], r["setting"]): r for r in saved}
    for q in questions:
        for setting in ("off", "require"):
            prev = latest.get((q["id"], setting))
            if prev and not prev["infra"]:
                continue
            result = run_agent(q["question"], llm, registry, uncited=setting)
            infra = failed_for_infrastructure(result)
            loose = uncited_substantive(result.answer) if not result.refused else []
            faith = None
            if not result.refused and not infra:
                try:
                    faith = judge_answer(
                        result.answer, evidence_from_citations(result.citations), judge
                    ).faithfulness
                except DailyQuotaExhausted as exc:
                    print(f"STOPPED: judge daily quota used up; rerun later to resume.\n{exc}")
                    return 3
            row = {
                "id": q["id"],
                "setting": setting,
                "refused": result.refused,
                "infra": infra,
                "repairs": result.repairs,
                "loose": loose,
                "faithfulness": faith,
                "answer": result.answer,
            }
            latest[(q["id"], setting)] = row
            with B_STORE.open("a") as f:
                f.write(json.dumps(row) + "\n")
            print(
                f"{q['id']:<4} {setting:<8} refused={result.refused!s:<5} repairs={result.repairs} loose={len(loose)} faith={faith}",
                flush=True,
            )
            time.sleep(4)
    rows = list(latest.values())
    faithfulness = {}
    for s in ("off", "require"):
        vals = [
            r["faithfulness"] for r in rows if r["setting"] == s and r["faithfulness"] is not None
        ]
        faithfulness[s] = sum(vals) / len(vals) if vals else 0.0
    for s in ("off", "require"):
        rs = [r for r in rows if r["setting"] == s]
        print(
            f"{s:<8} answers with uncited substantive sentence: {sum(1 for r in rs if r['loose'])}/{len(rs)}  refused: {sum(r['refused'] for r in rs)}  repairs: {sum(r['repairs'] for r in rs)}  mean faithfulness: {faithfulness[s]:.3f}"
        )
    ok, failures = guard_b(rows, faithfulness)
    print("\nEVALUATION B => " + ("PASS" if ok else "FAIL: " + "; ".join(failures)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(
        {"a": run_a, "b": run_b}[sys.argv[1]]() if len(sys.argv) == 2 and sys.argv[1] in "ab" else 2
    )
