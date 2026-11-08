"""Step 2 of PROTOCOL.md: score the product-default agent's real answers with the validated judge.

  uv run --group local-embed python -m evals.judge.run_answers     # resumable; needs DB, corpus, GEMINI_API_KEY

Each finished question is saved to answers_run1.jsonl immediately; a rerun skips what is done.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from evals.judge.judge import (
    JUDGE_MODEL,
    AnswerJudgement,
    DailyQuotaExhausted,
    GenaiJudgeModel,
    judge_answer,
)
from evals.judge.questions import ANSWERABLE_V0_IDS, UNANSWERABLE
from evals.validate_golden import load_items
from services.agent.graph import AgentResult, run_agent
from services.agent.llm import GeminiLLM

HERE = Path(__file__).parent
STORE = HERE / "answers_run1.jsonl"


def evidence_from_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The judge indexes passages by citation number; rebuild that list from the cited passages."""
    if not citations:
        return []
    by_n = {int(c["passage"]): c for c in citations}
    return [by_n.get(n, {}) for n in range(1, max(by_n) + 1)]


def failed_for_infrastructure(result: AgentResult) -> bool:
    """A refusal caused by a failed model call is NOT the agent refusing correctly; it must not be scored as one."""
    return any(e.kind == "error" for e in result.trace)


def row_from(
    qid: str,
    kind: str,
    question: str,
    result: AgentResult,
    judged: AnswerJudgement | None,
    seconds: float,
) -> dict[str, Any]:
    return {
        "id": qid,
        "kind": kind,
        "question": question,
        "answer": result.answer,
        "refused": result.refused,
        "infra_error": failed_for_infrastructure(result),
        "steps": result.steps,
        "tool_calls": result.tool_calls,
        "repairs": result.repairs,
        "seconds": round(seconds, 1),
        "claims": []
        if judged is None
        else [
            {"text": c.text, "verdict": c.verdict, "reason": c.reason, "invalid": c.invalid}
            for c in judged.claims
        ],
        "uncited": [] if judged is None else judged.uncited,
        "faithfulness": None if judged is None else judged.faithfulness,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in rows if not r["infra_error"]]
    ans = [r for r in ok if r["kind"] == "answerable"]
    una = [r for r in ok if r["kind"] == "unanswerable"]
    answered = [r for r in ans if not r["refused"]]
    claims = [c for r in answered for c in r["claims"]]
    scored = [r["faithfulness"] for r in answered if r["faithfulness"] is not None]
    fabricated = [r for r in una if not r["refused"]]
    return {
        "infra_errors": len(rows) - len(ok),
        "answerable": {
            "n": len(ans),
            "answered": len(answered),
            "claims_judged": len(claims),
            "claims_supported": sum(1 for c in claims if c["verdict"] == "supported"),
            "mean_answer_faithfulness": (sum(scored) / len(scored)) if scored else None,
            "answers_with_an_unsupported_claim": sum(
                1 for r in answered if any(c["verdict"] != "supported" for c in r["claims"])
            ),
            "uncited_sentences": sum(len(r["uncited"]) for r in answered),
            "invalid_judge_replies": sum(1 for c in claims if c["invalid"]),
        },
        "unanswerable": {
            "n": len(una),
            "refused_correctly": len(una) - len(fabricated),
            "answered_instead": [r["id"] for r in fabricated],
        },
    }


def questions() -> list[tuple[str, str, str]]:
    v3, errs = load_items("evals/golden/golden_v3_heldout.yaml")
    v0, errs0 = load_items("evals/golden/golden_v0.yaml")
    assert not errs and not errs0
    out = [(i.id, "answerable", i.question) for i in v3 if i.answer_type != "refusal"]
    out += [(i.id, "answerable", i.question) for i in v0 if i.id in ANSWERABLE_V0_IDS]
    out += [(f"u{n:02d}", "unanswerable", q) for n, q in enumerate(UNANSWERABLE, 1)]
    return out


def main() -> int:
    load_dotenv(".env")
    from services.tools.bootstrap import registry_from_env

    registry = registry_from_env()
    agent_llm = GeminiLLM(os.environ["GEMINI_API_KEY"])
    judge_model = GenaiJudgeModel(os.environ["GEMINI_API_KEY"])
    saved = [json.loads(line) for line in STORE.read_text().splitlines()] if STORE.exists() else []
    latest = {
        r["id"]: r for r in saved
    }  # a later row replaces an earlier one for the same question
    rows = list(latest.values())
    done = {
        i for i, r in latest.items() if not r["infra_error"]
    }  # infrastructure failures are re-run
    todo = [q for q in questions() if q[0] not in done]
    print(f"{len(done)} done, {len(todo)} to run; judge={JUDGE_MODEL}")
    for qid, kind, question in todo:
        start = time.perf_counter()
        result = run_agent(
            question, agent_llm, registry
        )  # product defaults: hardened prompt, L1 enforced
        judged = None
        if not result.refused:
            try:
                judged = judge_answer(
                    result.answer, evidence_from_citations(result.citations), judge_model
                )
            except DailyQuotaExhausted as exc:
                print(f"STOPPED: judge daily quota used up; rerun later to resume.\n{exc}")
                return 3
        row = row_from(qid, kind, question, result, judged, time.perf_counter() - start)
        rows = [r for r in rows if r["id"] != qid] + [row]
        with STORE.open("a") as f:
            f.write(json.dumps(row) + "\n")
        flag = (
            "INFRA-ERROR"
            if row["infra_error"]
            else ("refused" if row["refused"] else f"faith={row['faithfulness']}")
        )
        print(
            f"{qid:<14} {kind:<12} {flag:<14} steps={row['steps']} calls={row['tool_calls']} {question[:55]}"
        )
        time.sleep(4)
    print("\n" + json.dumps(summarize(rows), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
