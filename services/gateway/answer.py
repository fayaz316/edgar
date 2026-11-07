"""Answer generation: grounded prompt construction + citation validation.

Pure functions only (no IO) — the testable heart of the /ask endpoint.
Contract with the model:
  * answer ONLY from numbered passages; cite every claim as [n]
  * numbers/quotes must come from a passage
  * insufficient passages -> refuse explicitly
We then validate citations exist in OUR set; dangling [n] -> refused answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.gateway.retrieval import RetrievedChunk

CITATION_RE = re.compile(r"\[(\d{1,2})\]")

SYSTEM_PROMPT = """You are a research-analyst assistant over SEC filings (10-K / 10-Q).

Rules, in priority order:
1. Answer ONLY using the numbered passages provided. Every factual sentence must
   end with a citation like [1] or [2][3]. Multiple citations allowed.
2. If the passages do not contain the answer, reply exactly:
   INSUFFICIENT_CONTEXT — and one short sentence on what's missing.
3. Never invent numbers, dates, names, or quotes. If a passage is ambiguous,
   say so.
4. Be concise: 2-6 sentences unless the question demands more.
"""


@dataclass(frozen=True)
class GroundedAnswer:
    answer: str
    refused: bool
    cited_passages: list[int]  # 1-based passage numbers, validated to exist
    dangling_citations: list[int]  # cited but not in our set (stripped -> refusal)


def build_passages(chunks: list[RetrievedChunk]) -> str:
    lines: list[str] = []
    for n, c in enumerate(chunks, start=1):
        header = f"[{n}] {c.ticker} {c.form_type} filed {c.filed_at} — {c.section}"
        lines.append(f"{header}\n{'-' * len(header)}\n{c.text}")
    return "\n\n".join(lines)


def extract_citations(answer: str) -> list[int]:
    """All [n] numbers in the answer text, order preserved, deduped."""
    seen: dict[int, None] = {}
    for m in CITATION_RE.finditer(answer):
        seen.setdefault(int(m.group(1)), None)
    return list(seen)


def validate_answer(answer: str, n_passages: int) -> GroundedAnswer:
    """Enforce the grounding contract post-hoc. Dangling citation -> refusal."""
    if answer.strip().upper().startswith("INSUFFICIENT_CONTEXT"):
        return GroundedAnswer(
            answer=answer.strip(), refused=True, cited_passages=[], dangling_citations=[]
        )
    cited = extract_citations(answer)
    valid = [n for n in cited if 1 <= n <= n_passages]
    dangling = [n for n in cited if n not in valid]
    if dangling:
        # a hallucinated reference invalidates trust in the whole answer
        refusal = (
            "INSUFFICIENT_CONTEXT — the model cited passages outside the provided "
            f"evidence set ({dangling}); answer suppressed for safety."
        )
        return GroundedAnswer(
            answer=refusal, refused=True, cited_passages=[], dangling_citations=dangling
        )
    if not valid:
        refusal = (
            "INSUFFICIENT_CONTEXT — the model produced no valid passage citations; "
            "answer suppressed for safety."
        )
        return GroundedAnswer(
            answer=refusal, refused=True, cited_passages=[], dangling_citations=[]
        )
    return GroundedAnswer(
        answer=answer.strip(), refused=False, cited_passages=valid, dangling_citations=[]
    )
