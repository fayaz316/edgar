"""Ask the agent a question from the command line and print its trace.

uv run --group local-embed python -m services.agent.run "Compare NVIDIA and Apple supply-chain risk"
"""

from __future__ import annotations

import os
import sys

from services.agent.graph import run_agent
from services.agent.llm import GeminiLLM
from services.tools.bootstrap import registry_from_env


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    question = " ".join(sys.argv[1:])
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        from dotenv import load_dotenv

        load_dotenv(".env")
        key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        print("GEMINI_API_KEY missing (check .env)", file=sys.stderr)
        return 1
    result = run_agent(question, GeminiLLM(key), registry_from_env())
    print(f"\nQUESTION: {question}\n\nTRACE")
    for i, e in enumerate(result.trace, 1):
        print(f"  {i:>2}. [{e.kind:<6}] {e.detail}  ({e.seconds:.2f}s)")
    print(
        f"\nANSWER (refused={result.refused}, model turns={result.steps}, "
        f"tool calls={result.tool_calls}, repairs={result.repairs}):\n{result.answer}\n"
    )
    for c in result.citations:
        print(
            f"  [{c['passage']}] {c['ticker']} {c['form_type']} {c['filed_at']} {c['section']}"
            f" | {c['excerpt'][:100]!r}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
