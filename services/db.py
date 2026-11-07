"""Small DB helpers shared by scripts."""

from __future__ import annotations

import psycopg

MIGRATE_HINT = "chunks.embedding_model is missing — run `make db-migrate` (stop any running `make embed` first)."


def has_embedding_model_column(conn: psycopg.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'chunks' AND column_name = 'embedding_model'
        """
    ).fetchone()
    return row is not None
