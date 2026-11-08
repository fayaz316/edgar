"""Second-model cross-check of the judge (CROSSCHECK.md): sample "supported" claims and pull the best passages for each.

  uv run --group local-embed python -m evals.judge.crosscheck_sample

The original run did not store the passages each claim was judged against, so this check is WEAKER than re-reading the
judge's own evidence: it asks whether the filings support the claim at all (top 3 passages from the product retriever,
queried with the claim text). Writes evals/judge/crosscheck_items.jsonl.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

from services.embeddings import make_embedder
from services.gateway.retrieval import Retriever

load_dotenv(".env")
N, TOP = 25, 3
OUT = Path("evals/judge/crosscheck_items.jsonl")


def main() -> None:
    rows = [
        json.loads(line) for line in Path("evals/judge/answers_run1.jsonl").read_text().splitlines()
    ]
    claims = [
        {
            "answer_id": r["id"],
            "question": r["question"],
            "claim": c["text"],
            "judge_verdict": c["verdict"],
        }
        for r in rows
        for c in r.get("claims", [])
        if c["verdict"] == "supported"
    ]
    claims.sort(key=lambda c: hashlib.md5(f"{c['claim']}crosscheck".encode()).hexdigest())
    sample = claims[:N]
    embedder = make_embedder("local")
    with ConnectionPool(
        os.environ["DATABASE_URL"], min_size=1, max_size=2, kwargs={"autocommit": True}, open=True
    ) as pool:
        retriever = Retriever(pool, embedder)
        with OUT.open("w") as f:
            for c in sample:
                got = retriever.retrieve(c["claim"], top_k=TOP)
                c["passages"] = [
                    {
                        "filing": f"{p.ticker} {p.form_type} {p.filed_at}",
                        "section": p.section,
                        "text": p.text,
                    }
                    for p in got
                ]
                f.write(json.dumps(c) + "\n")
    print(f"wrote {len(sample)} of {len(claims)} supported claims to {OUT}")


if __name__ == "__main__":
    main()
