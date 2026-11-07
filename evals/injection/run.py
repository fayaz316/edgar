"""Run the prompt-injection evaluation ONCE per prompt variant (protocol: PROTOCOL.md).

uv run python -m evals.injection.run            # needs GEMINI_API_KEY; ~25 agent runs on the free tier
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from evals.injection.attacks import ATTACKS, BENIGN, GENUINE, QUESTION
from services.agent.graph import AgentResult, run_agent
from services.agent.llm import GeminiLLM
from services.gateway.retrieval import RetrievedChunk
from services.tools.filings import ToolContext, build_registry
from services.tools.registry import ToolRegistry

OUT = Path(__file__).parent / "results_run1.json"


def _chunk(cid: int, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        ticker="NVDA",
        form_type="10-Q",
        filed_at="2026-08-26",
        section="Risk Factors",
        text=text,
        rrf_score=0.1,
        lexical_rank=1,
        semantic_rank=1,
        accession="0001045810-26-000075",
    )


class FixedRetriever:
    def __init__(self, texts: list[str]) -> None:
        self.chunks = [_chunk(100 + i, t) for i, t in enumerate(texts)]

    def retrieve(self, query: str, **_: Any) -> list[RetrievedChunk]:
        return self.chunks


def _registry(texts: list[str]) -> ToolRegistry:
    return build_registry(ToolContext(retriever=FixedRetriever(texts), pool=None))  # type: ignore[arg-type]


def _run(llm: GeminiLLM, question: str, texts: list[str], variant: str) -> AgentResult:
    time.sleep(3)  # free tier: 15 requests/minute
    return run_agent(question, llm, _registry(texts), prompt_variant=variant, max_repairs=1)  # type: ignore[arg-type]


def main() -> int:
    load_dotenv(".env")
    llm = GeminiLLM(os.environ["GEMINI_API_KEY"])
    report: dict[str, Any] = {}
    for variant in ("v0", "v1"):
        rows = []
        for a in ATTACKS:
            r = _run(llm, QUESTION, [a.payload, GENUINE], variant)  # injected passage FIRST
            rows.append(
                {
                    "id": a.id,
                    "kind": a.kind,
                    "success": a.succeeded(r),
                    "refused": r.refused,
                    "cited": len(r.citations),
                    "answer": r.answer[:260],
                }
            )
            print(
                f"{variant} {a.id:<15} attack {'SUCCEEDED' if rows[-1]['success'] else 'failed   '}  refused={r.refused} cited={len(r.citations)}"
            )
        utility = []
        for q in BENIGN:
            r = _run(llm, q, [GENUINE], variant)
            utility.append(not r.refused and len(r.citations) >= 1)
            print(f"{variant} benign: {'ok' if utility[-1] else 'FAILED'}  {q[:60]}")
        report[variant] = {
            "attacks": rows,
            "asr": sum(1 for x in rows if x["success"]) / len(rows),
            "utility": sum(utility) / len(utility),
        }
    OUT.write_text(json.dumps(report, indent=1))
    for v, d in report.items():
        print(
            f"\n{v}: ASR {sum(x['success'] for x in d['attacks'])}/{len(d['attacks'])}   utility {d['utility']:.2f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
