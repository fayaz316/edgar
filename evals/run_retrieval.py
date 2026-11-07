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
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool

from evals.matching import (
    Equivalents,
    RankedChunk,
    anchors_covered,
    first_hit_rank,
    section_agrees,
    summarize,
)
from evals.schema import GoldenItem
from evals.validate_golden import GOLDEN_PATH, load_items
from services.db import MIGRATE_HINT, has_embedding_model_column
from services.embeddings import MODEL_IDS, EmbeddingError, make_embedder
from services.gateway.rerank import CrossEncoderReranker
from services.gateway.retrieval import Retriever

load_dotenv(".env")
KEYWORD_MODES: dict[str, Literal["and", "or", "bm25"]] = {
    "all": "and",
    "any": "or",
    "bm25": "bm25",
}
PAUSE_S = 0.8  # stay far below the 100 RPM embedding quota
QUOTA_WAIT_S = 65.0


def embedded_coverage(pool: ConnectionPool, model_id: str) -> tuple[int, int]:
    """(chunks embedded by THIS model, all chunks)."""
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT count(*) FILTER (WHERE embedding_model = %s), count(*) FROM chunks", (model_id,)
        ).fetchone()
    return (int(row[0]), int(row[1])) if row else (0, 0)


def corpus_fingerprint(pool: ConnectionPool) -> str:
    """Hash of every chunk's text in a stable order: two runs are comparable only on the same corpus."""
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT md5(string_agg(md5(c.text), '' ORDER BY d.accession, c.section, c.seq)) "
            "FROM chunks c JOIN documents d ON d.id = c.document_id"
        ).fetchone()
    return str(row[0]) if row else ""


def company_equivalents(pool: ConnectionPool) -> Equivalents:
    """accession -> every accession of the same ticker (lenient scoring: same company's text)."""
    with pool.connection() as conn:
        rows = conn.execute("SELECT ticker, accession FROM documents").fetchall()
    by_ticker: dict[str, set[str]] = defaultdict(set)
    for ticker, accession in rows:
        by_ticker[str(ticker)].add(str(accession))
    return {acc: frozenset(accs) for accs in by_ticker.values() for acc in accs}


def retrieve_ranked(
    retriever: Retriever, item: GoldenItem, k: int, infer_filing: bool = True
) -> list[RankedChunk]:
    for attempt in range(3):
        try:
            got = retriever.retrieve(item.question, top_k=k, infer_filing=infer_filing)
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
    ap.add_argument("--golden", default=GOLDEN_PATH, help="golden YAML to score")
    ap.add_argument("--out", default="evals/results/latest.json")
    ap.add_argument(
        "--embedder", choices=sorted(MODEL_IDS), default=os.environ.get("EA_EMBEDDER", "local")
    )
    ap.add_argument(
        "--lexical",
        choices=tuple(KEYWORD_MODES),
        default=None,
        help="keyword leg; omit to use the product default (bm25, ADR 0010) | all = old AND | any = OR",
    )
    ap.add_argument(
        "--no-filing-hints",
        action="store_true",
        help="do not read form type / 'latest' from the question (for before/after comparison)",
    )
    ap.add_argument(
        "--rerank",
        action="store_true",
        help="rescore the top 30 fused chunks with the cross-encoder (Addendum G; off by default)",
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

    items, errors = load_items(args.golden)
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

        reranker = CrossEncoderReranker() if args.rerank else None
        # no flag -> the Retriever's own defaults, so the gate tests what the product actually does
        options: dict[str, Any] = {"reranker": reranker}
        if args.lexical:
            options["keyword"] = KEYWORD_MODES[args.lexical]
        retriever = Retriever(pool, embedder, **options)
        equivalents = company_equivalents(pool)
        fingerprint = corpus_fingerprint(pool)
        rows: list[dict[str, object]] = []
        ranks: list[int | None] = []
        lenient_ranks: list[int | None] = []
        types: list[str] = []
        for n, item in enumerate(scored, start=1):
            ranked = retrieve_ranked(retriever, item, args.k, not args.no_filing_hints)
            rank = first_hit_rank(ranked, item.expected_evidence)
            ranks.append(rank)
            lenient = first_hit_rank(ranked, item.expected_evidence, equivalents)
            lenient_ranks.append(lenient)
            types.append(item.answer_type)
            found, need = anchors_covered(ranked, item.expected_evidence, args.k)
            rows.append(
                {
                    "id": item.id,
                    "answer_type": item.answer_type,
                    "difficulty": item.difficulty,
                    "rank": rank,
                    "rank_lenient": lenient,
                    "anchors_found": found,
                    "anchors_needed": need,
                    "section_agrees": section_agrees(ranked, item.expected_evidence),
                }
            )
            print(f"[{n:>2}/{len(scored)}] {item.id:<16} rank={rank}  anchors={found}/{need}")
            time.sleep(PAUSE_S)

    ks = tuple(k for k in (1, 3, 5, 8) if k <= args.k)
    overall = summarize(ranks, ks=ks)
    overall_lenient = summarize(lenient_ranks, ks=ks)
    by_type: dict[str, list[int | None]] = defaultdict(list)
    for t, r in zip(types, ranks, strict=True):
        by_type[t].append(r)

    print(f"\n=== retrieval recall over {len(rows)} answerable questions (k={args.k}) ===")
    print("overall :", {m: round(v, 3) for m, v in overall.items()}, " (strict: exact filing)")
    print(
        "lenient :",
        {m: round(v, 3) for m, v in overall_lenient.items()},
        " (same company, any filing)",
    )
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
                "corpus_fingerprint": fingerprint,
                "config": {
                    "lexical": retriever.keyword,
                    "rerank": bool(args.rerank),
                    "filing_hints": not args.no_filing_hints,
                },
                "overall": overall,
                "overall_lenient": overall_lenient,
                "rerank_seconds_median": (
                    round(statistics.median(reranker.timings), 3)
                    if reranker and reranker.timings
                    else None
                ),
                "rows": rows,
            },
            indent=2,
        )
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
