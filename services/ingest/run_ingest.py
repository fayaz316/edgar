"""Ingest CLI: filings for tickers → local (later: cloud) Postgres.

Usage: uv run python -m services.ingest.run_ingest NVDA AAPL JPM

Idempotent by design: upsert document on (ticker, accession); a refresh
deletes that document's chunks and re-inserts. Rerun freely.
"""

from __future__ import annotations

import os
import sys

import psycopg
from dotenv import load_dotenv

from services.ingest.edgar_client import EdgarClient, Filing
from services.ingest.parse import parse_filing

load_dotenv()  # .env at repo root: DATABASE_URL

FORMS = frozenset({"10-K", "10-Q"})


def store_filing(cur: psycopg.Cursor, filing: Filing, html: str) -> tuple[int, int]:
    """Upsert the document row, refresh its chunks. Returns (doc_id, n_chunks)."""
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

    cur.execute("DELETE FROM chunks WHERE document_id = %s", (doc_id,))

    chunks = parse_filing(html)
    cur.executemany(
        """
        INSERT INTO chunks (document_id, section, seq, text)
        VALUES (%s, %s, %s, %s)
        """,
        [(doc_id, c.section, c.seq, c.text) for c in chunks],
    )
    return doc_id, len(chunks)


def main(tickers: list[str]) -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL missing (check .env)", file=sys.stderr)
        return 1

    client = EdgarClient()
    total_chunks = 0
    with psycopg.connect(database_url) as conn:
        for ticker in tickers:
            filings = client.recent_filings(ticker, FORMS)
            print(f"{ticker}: {len(filings)} filings ({', '.join(f.form for f in filings)})")
            for filing in filings:
                html = client.filing_document(filing)
                with conn.cursor() as cur:
                    doc_id, n = store_filing(cur, filing, html)
                conn.commit()
                total_chunks += n
                print(
                    f"  {filing.form} {filing.filed_at} acc={filing.accession} -> doc {doc_id}, {n} chunks"
                )
    client.close()
    print(f"TOTAL chunks ingested: {total_chunks}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
