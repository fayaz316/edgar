"""Embedding backfill: chunks.embedding <- the ACTIVE embedder (gemini | local).

Selects every chunk whose vector is missing OR was made by a different model than the
active one, embeds it, and stores vector + model tag together. So:
  * resumable and ctrl-C safe (commit per batch; reruns pick up where it stopped)
  * switching providers = rerun with the other one; nothing is ever mixed
  * quota pain is handled by the provider (gemini: waits out per-minute windows) plus an
    adaptive batch size here (halve on persistent failure, floor 10)

Usage: uv run python -m services.ingest.embed_backfill [--embedder gemini|local]
       (local needs:  uv sync --group local-embed)
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import psycopg
import structlog
from dotenv import load_dotenv

from services.db import MIGRATE_HINT, has_embedding_model_column
from services.embeddings import MODEL_IDS, EmbeddingError, make_embedder

load_dotenv(".env")
log = structlog.get_logger()

BATCH_MIN = 10
PENDING = "(embedding IS NULL OR embedding_model IS DISTINCT FROM %s)"


def to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vec) + "]"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--embedder", choices=sorted(MODEL_IDS), default=os.environ.get("EA_EMBEDDER", "local")
    )
    args = ap.parse_args(argv)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL missing (check .env)", file=sys.stderr)
        return 1
    embedder = make_embedder(args.embedder, api_key=os.environ.get("GEMINI_API_KEY"))
    model_id = embedder.model_id
    batch_size = embedder.batch_size
    log.info("backfill_start", embedder=args.embedder, model=model_id, batch_size=batch_size)

    done = 0
    with psycopg.connect(database_url) as conn:
        if not has_embedding_model_column(conn):
            print(MIGRATE_HINT, file=sys.stderr)
            return 3
        conn.commit()
        while True:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT id, text FROM chunks WHERE {PENDING} ORDER BY id LIMIT %s",
                    (model_id, batch_size),
                )
                rows = cur.fetchall()
            conn.commit()
            if not rows:
                log.info("backfill_complete", total_embedded=done, model=model_id)
                return 0

            ids, texts = [r[0] for r in rows], [r[1] for r in rows]
            t0 = time.monotonic()
            try:
                vectors = embedder.embed_documents(texts)
            except EmbeddingError as exc:
                if batch_size > BATCH_MIN:
                    batch_size = max(batch_size // 2, BATCH_MIN)
                    log.warning("batch_reduced", new_batch_size=batch_size, error=str(exc)[:120])
                    continue
                log.error(
                    "backfill_stalled",
                    hint="quota or model problem; rerun later",
                    error=str(exc)[:200],
                )
                return 2

            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE chunks SET embedding = %s::vector, embedding_model = %s WHERE id = %s",
                    [(to_pgvector(v), model_id, cid) for v, cid in zip(vectors, ids, strict=True)],
                )
                cur.execute(f"SELECT count(*) FROM chunks WHERE {PENDING}", (model_id,))
                row = cur.fetchone()
            conn.commit()
            remaining = int(row[0]) if row else 0
            done += len(ids)
            log.info(
                "batch_ok",
                embedded=done,
                remaining=remaining,
                batch_size=len(ids),
                embed_s=round(time.monotonic() - t0, 1),
            )
            if remaining and embedder.pause_s:
                time.sleep(embedder.pause_s)


if __name__ == "__main__":
    sys.exit(main())
