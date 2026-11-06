"""Embedding backfill: chunks.embedding <- gemini-embedding-001 (768d).

Free-tier quota is the design constraint (100 RPM / 30K TPM / 1K RPD):
  * start at 50 chunks/batch (~worst-case 20K tokens — token estimates are
    estimates; quota is enforced server-side, so stay conservative)
  * 429 means "the minute window is spent" -> wait >=65s, never fast-retry
  * persistent 429 -> halve batch size (floor 10) and continue
  * resumable: only NULL-embedding rows selected; commit per batch

Usage: uv run python -m services.ingest.embed_backfill   (ctrl-C safe)
"""

from __future__ import annotations

import os
import sys
import time

import psycopg
import structlog
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv(".env")
log = structlog.get_logger()

MODEL = "gemini-embedding-001"
DIMS = 768
BATCH_START = 50
BATCH_MIN = 10
SECONDS_BETWEEN_BATCHES = 62
MAX_ATTEMPTS = 6


class QuotaExceeded(RuntimeError):
    pass


def embed_batch(client: genai.Client, texts: list[str]) -> list[list[float]]:
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = client.models.embed_content(
                model=MODEL,
                contents=texts,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=DIMS,
                ),
            )
            if resp.embeddings is None or len(resp.embeddings) != len(texts):
                raise RuntimeError(
                    f"embedding count mismatch: {len(resp.embeddings or [])} vs {len(texts)}"
                )
            out: list[list[float]] = []
            for e in resp.embeddings:
                if e.values is None:
                    raise RuntimeError("embedding vector is None")
                out.append(list(e.values))
            return out
        except Exception as exc:  # classified below: quota vs transient, distinct waits
            last_error = exc
            msg = str(exc)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                # per-minute quota: any wait < 60s is wasted retry
                wait = 65.0
                log.warning("quota_429", attempt=attempt + 1, wait_s=wait, batch=len(texts))
            else:
                wait = min(2.0**attempt * 2, 60)
                log.warning("embed_retry", attempt=attempt + 1, wait_s=wait, error=msg[:160])
            time.sleep(wait)
    raise QuotaExceeded(f"embedding failed after {MAX_ATTEMPTS} attempts: {str(last_error)[:200]}")


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not database_url or not api_key:
        print("DATABASE_URL / GEMINI_API_KEY missing (check .env)", file=sys.stderr)
        return 1

    client = genai.Client(api_key=api_key)
    batch_size = BATCH_START
    done = 0
    with psycopg.connect(database_url) as conn:
        while True:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, text FROM chunks WHERE embedding IS NULL ORDER BY id LIMIT %s",
                    (batch_size,),
                )
                rows = cur.fetchall()
            if not rows:
                log.info("backfill_complete", total_embedded=done)
                return 0

            ids, texts = [r[0] for r in rows], [r[1] for r in rows]
            t0 = time.monotonic()
            try:
                vectors = embed_batch(client, texts)
            except QuotaExceeded:
                if batch_size > BATCH_MIN:
                    batch_size = max(batch_size // 2, BATCH_MIN)
                    log.warning("batch_reduced", new_batch_size=batch_size)
                    continue
                log.error("backfill_stalled", hint="daily quota may be exhausted; rerun later")
                return 2

            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE chunks SET embedding = %s::vector WHERE id = %s",
                    [
                        ("[" + ",".join(f"{v:.6f}" for v in vec) + "]", cid)
                        for vec, cid in zip(vectors, ids, strict=True)
                    ],
                )
            conn.commit()
            done += len(ids)
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM chunks WHERE embedding IS NULL")
                row = cur.fetchone()
                remaining = int(row[0]) if row else 0
            log.info(
                "batch_ok",
                embedded=done,
                remaining=remaining,
                batch_size=len(ids),
                embed_s=round(time.monotonic() - t0, 1),
            )
            time.sleep(SECONDS_BETWEEN_BATCHES)


if __name__ == "__main__":
    sys.exit(main())
