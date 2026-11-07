"""Hybrid retrieval: lexical (ts_rank) + semantic (pgvector cosine) fused by RRF.

Why hybrid: lexical catches exact terms (tickers, "Item 1A", product names);
semantic catches paraphrase ("demand worries" ~ "concentration of revenue").
RRF fuses by rank position only — no score-scale calibration between
incompatible metrics (ts_rank vs cosine distance).
"""

from __future__ import annotations

from dataclasses import dataclass

from google import genai
from google.genai import types
from psycopg_pool import ConnectionPool

EMBED_MODEL = "gemini-embedding-001"
RRF_K = 60  # standard constant from the original RRF paper; dampens rank position
POOL_PER_LEG = 30  # candidates fetched per leg before fusion


class EmbeddingError(RuntimeError):
    """Query embedding failed (quota, network, bad response) — distinct from DB errors
    so the API can map it to 502 (upstream) instead of 500 (our bug)."""


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    ticker: str
    form_type: str
    filed_at: str
    section: str
    text: str
    rrf_score: float
    lexical_rank: int | None  # 1-based rank in lexical leg; None = not found there
    semantic_rank: int | None
    accession: str  # SEC accession number — lets evals match chunks to golden anchors


def rrf_fuse(
    lexical: list[int], semantic: list[int], k: int = RRF_K
) -> dict[int, tuple[float, int | None, int | None]]:
    """Fuse two ranked id lists. Returns {id: (rrf_score, lex_rank, sem_rank)}."""
    scores: dict[int, tuple[float, int | None, int | None]] = {}

    def add(ids: list[int], which: int) -> None:
        for pos, cid in enumerate(ids, start=1):
            score, lex, sem = scores.get(cid, (0.0, None, None))
            score += 1.0 / (k + pos)
            if which == 0:
                lex = pos
            else:
                sem = pos
            scores[cid] = (score, lex, sem)

    add(lexical, 0)
    add(semantic, 1)
    return scores


class Retriever:
    """Hybrid retriever. Borrows a pooled autocommit connection per call, so one
    failed query can never poison a shared transaction for the next request."""

    def __init__(self, pool: ConnectionPool, genai_client: genai.Client) -> None:
        self._pool = pool
        self._genai = genai_client

    def _embed_query(self, query: str) -> list[float]:
        try:
            resp = self._genai.models.embed_content(
                model=EMBED_MODEL,
                contents=query,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=768,
                ),
            )
        except Exception as exc:  # SDK raises many types; all mean "upstream failed"
            raise EmbeddingError(f"query embedding failed: {str(exc)[:150]}") from exc
        if resp.embeddings is None or not resp.embeddings or resp.embeddings[0].values is None:
            raise EmbeddingError("query embedding returned no vector")
        return list(resp.embeddings[0].values)

    def retrieve(
        self,
        query: str,
        top_k: int = 8,
        ticker: str | None = None,
        sections: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        """Hybrid retrieve. Filters compose with AND; None = no filter."""
        qvec = "[" + ",".join(f"{v:.6f}" for v in self._embed_query(query)) + "]"

        where = ["c.embedding IS NOT NULL"]
        params: list[str | list[str]] = []
        if ticker:
            where.append("d.ticker = %s")
            params.append(ticker.upper())
        if sections:
            where.append("c.section = ANY(%s)")
            params.append(sections)
        where_sql = " AND ".join(where)

        lexical_sql = f"""
            SELECT c.id, d.ticker, d.form_type, d.filed_at::date::text, c.section, c.text, d.accession
            FROM websearch_to_tsquery('english', %s) AS q(query),
                 chunks c JOIN documents d ON d.id = c.document_id
            WHERE {where_sql} AND c.tsv @@ q.query
            ORDER BY ts_rank_cd(c.tsv, q.query) DESC
            LIMIT {POOL_PER_LEG}
        """
        semantic_sql = f"""
            SELECT c.id, d.ticker, d.form_type, d.filed_at::date::text, c.section, c.text, d.accession
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE {where_sql}
            ORDER BY c.embedding <=> %s::vector
            LIMIT {POOL_PER_LEG}
        """

        with self._pool.connection() as conn, conn.cursor() as cur:
            cur.execute(lexical_sql, [query, *params])
            lex_rows = cur.fetchall()
            cur.execute(semantic_sql, [*params, qvec])
            sem_rows = cur.fetchall()

        by_id: dict[int, tuple[str, str, str, str, str, str]] = {
            r[0]: (r[1], r[2], r[3], r[4], r[5], r[6]) for r in [*lex_rows, *sem_rows]
        }
        fused = rrf_fuse([r[0] for r in lex_rows], [r[0] for r in sem_rows])
        ranked = sorted(fused.items(), key=lambda kv: kv[1][0], reverse=True)[:top_k]

        out: list[RetrievedChunk] = []
        for cid, (score, lex_rank, sem_rank) in ranked:
            ticker_, form, filed, section, text, accession = by_id[cid]
            out.append(
                RetrievedChunk(
                    chunk_id=cid,
                    ticker=ticker_,
                    form_type=form,
                    filed_at=filed,
                    section=section,
                    text=text,
                    rrf_score=round(score, 6),
                    lexical_rank=lex_rank,
                    semantic_rank=sem_rank,
                    accession=accession,
                )
            )
        return out
