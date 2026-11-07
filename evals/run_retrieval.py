"""Retrieval-only eval: does the right passage land in the top-k? (no generation calls)

Why retrieval alone first: generation quality can't exceed retrieval quality, and this
costs one embedding call per question — no generation quota, no judge model. Run it
before and after every parser/chunking/retriever change; the delta IS the story.

A question "hits" at rank r when the r-th retrieved chunk is from an anchor's filing and
contains its snippet_hint (see evals/matching.py). Refusal questions are skipped here —
their correctness is a generation-time behaviour, scored in Phase 3.

Usage: uv run python -m evals.run_retrieval [--k 8] [--out evals/results/baseline.json]
                                            [--allow-partial]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

from evals.matching import RankedChunk, anchors_covered, first_hit_rank, section_agrees, summarize
from evals.schema import GoldenItem
from evals.validate_golden import load_items
from services.db import MIGRATE_HINT, has_embedding_model_column
from services.embeddings import MODEL_IDS, EmbeddingError, make_embedder
from services.gateway.retrieval import Retriever

load_dotenv(".env")
PAUSE_S = 0.8  # stay far below the 100 RPM embedding quota
QUOTA_WAIT_S = 65.0


def embedded_coverage(pool: ConnectionPool, model_id: str) -> tuple[int, int]:
    """(chunks embedded by THIS model, all chunks)."""
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT count(*) FILTER (WHERE embedding_model = %s), count(*) FROM chunks", (model_id,)
        ).fetchone()
    return (int(row[0]), int(row[1])) if row else (0, 0)


def retrieve_ranked(retriever: Retriever, item: GoldenItem, k: int) -> list[RankedChunk]:
    for attempt in range(3):
        try:
            got = retriever.retrieve(item.question, top_k=k)
            return [(c.accession, c.section, c.text) for c in got]
        except EmbeddingError as exc:
            if attempt == 2:
                raise
            print(f"  embed error ({str(exc)[:80]}), waiting {QUOTA_WAIT_S:.0f}s", file=sys.stderr)
            time.sleep(QUOTA_WAIT_S)
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--out", default="evals/results/latest.json")
    ap.add_argument(
        "--embedder", choices=sorted(MODEL_IDS), default=os.environ.get("EA_EMBEDDER", "local")
    )
    ap.add_argument(
        "--allow-partial", action="store_true", help="run even if embeddings incomplete"
    )
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL missing (check .env)", file=sys.stderr)
        return 1
    embedder = make_embedder(args.embedder, api_key=os.environ.get("GEMINI_API_KEY"))

    items, errors = load_items()
    if errors:
        print("golden set invalid — run evals.validate_golden first", file=sys.stderr)
        return 1
    scored = [i for i in items if i.answer_type != "refusal"]

    with ConnectionPool(
        dsn, min_size=1, max_size=2, kwargs={"autocommit": True}, open=True
    ) as pool:
        with pool.connection() as _c:
            if not has_embedding_model_column(_c):
                print(MIGRATE_HINT, file=sys.stderr)
                return 3
        embedded, total = embedded_coverage(pool, embedder.model_id)
        if total == 0:
            print(
                "REFUSING: the chunks table is empty (DB wiped?). Rebuild it: "
                "`make reingest` (offline, from data/raw) then `make embed`.",
                file=sys.stderr,
            )
            return 2
        if embedded < total and not args.allow_partial:
            print(
                f"REFUSING: only {embedded}/{total} chunks embedded with {embedder.model_id} — recall on a partial corpus "
                "is meaningless. Finish `make embed` (or pass --allow-partial).",
                file=sys.stderr,
            )
            return 2

        retriever = Retriever(pool, embedder)
        rows: list[dict[str, object]] = []
        ranks: list[int | None] = []
        types: list[str] = []
        for n, item in enumerate(scored, start=1):
            ranked = retrieve_ranked(retriever, item, args.k)
            rank = first_hit_rank(ranked, item.expected_evidence)
            ranks.append(rank)
            types.append(item.answer_type)
            found, need = anchors_covered(ranked, item.expected_evidence, args.k)
            rows.append(
                {
                    "id": item.id,
                    "answer_type": item.answer_type,
                    "difficulty": item.difficulty,
                    "rank": rank,
                    "anchors_found": found,
                    "anchors_needed": need,
                    "section_agrees": section_agrees(ranked, item.expected_evidence),
                }
            )
            print(f"[{n:>2}/{len(scored)}] {item.id:<16} rank={rank}  anchors={found}/{need}")
            time.sleep(PAUSE_S)

    overall = summarize(ranks, ks=tuple(k for k in (1, 3, 5, 8) if k <= args.k))
    by_type: dict[str, list[int | None]] = defaultdict(list)
    for t, r in zip(types, ranks, strict=True):
        by_type[t].append(r)

    print(f"\n=== retrieval recall over {len(rows)} answerable questions (k={args.k}) ===")
    print("overall :", {m: round(v, 3) for m, v in overall.items()})
    for t, rs in sorted(by_type.items()):
        print(f"{t:<11}:", {m: round(v, 3) for m, v in summarize(rs, ks=(1, args.k)).items()})
    misses = [str(r["id"]) for r in rows if r["rank"] is None]
    print("misses  :", misses or "none")
    mismatched = [str(r["id"]) for r in rows if r["section_agrees"] is False]
    print("hit but section label differs from golden anchor:", mismatched or "none")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "k": args.k,
                "embedder": embedder.model_id,
                "corpus": {"embedded": embedded, "total": total},
                "overall": overall,
                "rows": rows,
            },
            indent=2,
        )
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
