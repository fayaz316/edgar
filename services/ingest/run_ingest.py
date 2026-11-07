"""Ingest CLI: filings for tickers -> raw-HTML cache -> local (later: cloud) Postgres.

Usage:
  uv run python -m services.ingest.run_ingest NVDA AAPL JPM            # fetch (cache-first) + store
  uv run python -m services.ingest.run_ingest NVDA AAPL JPM --fetch-only   # download only, no DB
  uv run python -m services.ingest.run_ingest --offline [NVDA ...]    # re-parse cached HTML, no network
  add --refresh to re-download even if cached

Idempotent by design: upsert the document on (ticker, accession); a refresh replaces that
document's chunks but REUSES the embedding of any chunk whose text is unchanged (an
embedding depends only on its text) — so relabeling sections or re-running costs no quota,
and only genuinely new text needs embedding.

Do NOT run this while `make embed` is running — both write the chunks table.
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg
from dotenv import load_dotenv

from services.db import MIGRATE_HINT, has_embedding_model_column
from services.embeddings import MODEL_IDS, model_id_for
from services.ingest import raw_cache
from services.ingest.edgar_client import EdgarClient, Filing
from services.ingest.parse import Chunk, parse_filing

load_dotenv()  # .env at repo root: DATABASE_URL

FORMS = frozenset({"10-K", "10-Q"})


def plan_chunk_rows(
    doc_id: int, chunks: list[Chunk], reusable: dict[str, str], model_id: str
) -> tuple[list[tuple[int, str, int, str, str | None, str | None]], int]:
    """Rows to INSERT for a document, plus how many reuse an existing embedding.

    An embedding is a pure function of (model, chunk text), so a chunk whose text is
    unchanged keeps its old vector even if its section label or seq changed. `reusable`
    must only hold vectors made by `model_id`; the model tag is stored only with a vector
    (the table CHECK constraint requires vector and tag to be present together).
    """
    rows = [
        (
            doc_id,
            c.section,
            c.seq,
            c.text,
            reusable.get(c.text),
            model_id if c.text in reusable else None,
        )
        for c in chunks
    ]
    return rows, sum(1 for r in rows if r[4] is not None)


def store_filing(
    cur: psycopg.Cursor, filing: Filing, html: str, model_id: str
) -> tuple[int, int, int]:
    """Upsert the document row, refresh its chunks.
    Returns (doc_id, n_chunks, n_embeddings_reused)."""
    cur.execute(
        """
        INSERT INTO documents (ticker, form_type, accession, period_end, filed_at, uri)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (ticker, accession) DO UPDATE
          SET form_type = EXCLUDED.form_type,
              period_end = EXCLUDED.period_end,
              filed_at   = EXCLUDED.filed_at,
              uri        = EXCLUDED.uri
        RETURNING id
        """,
        (
            filing.ticker,
            filing.form,
            filing.accession,
            filing.period_end,
            filing.filed_at,
            filing.document_url,
        ),
    )
    doc_id: int = cur.fetchone()[0]  # type: ignore[index]

    # Remember embeddings (made by the ACTIVE model only) by text before replacing the chunks.
    cur.execute(
        """
        SELECT text, embedding::text FROM chunks
        WHERE document_id = %s AND embedding IS NOT NULL AND embedding_model = %s
        """,
        (doc_id, model_id),
    )
    reusable: dict[str, str] = {text: emb for text, emb in cur.fetchall()}

    cur.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))

    rows, n_reused = plan_chunk_rows(doc_id, parse_filing(html, filing.form), reusable, model_id)
    cur.executemany(
        """
        INSERT INTO chunks (document_id, section, seq, text, embedding, embedding_model)
        VALUES (%s, %s, %s, %s, %s::vector, %s)
        """,
        rows,
    )
    return doc_id, len(rows), n_reused


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("tickers", nargs="*", help="e.g. NVDA AAPL JPM")
    ap.add_argument(
        "--fetch-only", action="store_true", help="download + cache HTML, skip the database"
    )
    ap.add_argument("--offline", action="store_true", help="use only cached filings (no network)")
    ap.add_argument("--refresh", action="store_true", help="re-download even if cached")
    ap.add_argument(
        "--embedder",
        choices=sorted(MODEL_IDS),
        default=os.environ.get("EA_EMBEDDER", "local"),
        help="whose existing embeddings may be reused (default: $EA_EMBEDDER or local)",
    )
    args = ap.parse_args(argv)

    if not args.offline and not args.tickers:
        ap.error("give tickers, or use --offline")
    if args.offline and args.fetch_only:
        ap.error("--offline and --fetch-only contradict each other")

    database_url = os.environ.get("DATABASE_URL")
    if not args.fetch_only and not database_url:
        print("DATABASE_URL missing (check .env)", file=sys.stderr)
        return 1

    # 1) decide which (filing, html) pairs to process
    pairs: list[tuple[Filing, str]] = []
    if args.offline:
        pairs = list(raw_cache.iter_cached(args.tickers or None))
        print(f"offline: {len(pairs)} cached filings")
    else:
        client = EdgarClient()
        try:
            for ticker in args.tickers:
                filings = client.recent_filings(ticker, FORMS)
                print(f"{ticker}: {len(filings)} filings ({', '.join(f.form for f in filings)})")
                for filing in filings:
                    cached = raw_cache.load(filing) is not None and not args.refresh
                    html = raw_cache.get_html(client, filing, refresh=args.refresh)
                    print(
                        f"  {filing.form} {filing.filed_at} {filing.accession}: {'cache' if cached else 'downloaded'}"
                    )
                    pairs.append((filing, html))
        finally:
            client.close()

    if args.fetch_only:
        print(f"fetched/cached {len(pairs)} filings under {raw_cache.RAW_DIR}/")
        return 0

    # 2) store
    assert database_url is not None
    model_id = model_id_for(args.embedder)
    total_chunks = total_reused = 0
    with psycopg.connect(database_url) as conn:
        if not has_embedding_model_column(conn):
            print(MIGRATE_HINT, file=sys.stderr)
            return 3
        conn.commit()
        for filing, html in pairs:
            with conn.cursor() as cur:
                doc_id, n, reused = store_filing(cur, filing, html, model_id)
            conn.commit()
            total_chunks += n
            total_reused += reused
            print(
                f"  {filing.ticker} {filing.form} {filing.filed_at} acc={filing.accession} "
                f"-> doc {doc_id}, {n} chunks ({reused} embeddings reused)"
            )
    print(
        f"TOTAL chunks: {total_chunks}  embeddings reused: {total_reused}  "
        f"need embedding: {total_chunks - total_reused}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
