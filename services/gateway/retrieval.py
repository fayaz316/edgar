"""Hybrid retrieval: lexical (ts_rank) + semantic (pgvector cosine) fused by RRF.

Why hybrid: lexical catches exact terms (tickers, "Item 1A", product names);
semantic catches paraphrase ("demand worries" ~ "concentration of revenue").
RRF fuses by rank position only — no score-scale calibration between
incompatible metrics (ts_rank vs cosine distance).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from psycopg_pool import ConnectionPool

from services.embeddings import Embedder
from services.gateway.bm25 import TermRow, bm25_rank
from services.gateway.filing_hints import FilingHints, parse_filing_hints
from services.gateway.rerank import RERANK_POOL, Reranker, reorder

_NEGATED_TERM = re.compile(
    r"(?<![\w-])-\w+"
)  # '-china' (hyphen at a word start), not 'export-control'
RRF_K = 60  # standard constant from the original RRF paper; dampens rank position
POOL_PER_LEG = 30  # candidates fetched per leg before fusion


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
    rerank_score: float | None = None  # cross-encoder score when a reranker is configured


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
    failed query can never poison a shared transaction for the next request.

    `keyword` picks the keyword leg: "bm25" (default, ADR 0010: ORed question terms ranked by BM25),
    "and" (the old leg: every question word must be in ONE chunk, so it is empty for most
    natural-language questions - ADR 0009) or "or" (ORed terms ranked by ts_rank_cd; rejected,
    ADR 0009). The older modes stay for before/after comparison.

    Only vectors tagged with the ACTIVE embedder's model_id are searched: vectors from
    different models are not comparable, and mixing them returns plausible-looking nonsense.
    """

    def __init__(
        self,
        pool: ConnectionPool,
        embedder: Embedder,
        *,
        keyword: Literal["and", "or", "bm25"] = "bm25",
        reranker: Reranker | None = None,
        rerank_pool: int = RERANK_POOL,
    ) -> None:
        self._pool = pool
        self._embedder = embedder
        self._keyword = keyword
        self._reranker = reranker  # off by default: see ADR 0011
        self._rerank_pool = rerank_pool
        self._corpus: tuple[int, float] | None = None  # (chunk count, mean chunk length)

    @property
    def keyword(self) -> str:
        return self._keyword

    def retrieve(
        self,
        query: str,
        top_k: int = 8,
        ticker: str | None = None,
        sections: list[str] | None = None,
        form_type: str | None = None,
        latest: bool | None = None,
        infer_filing: bool = True,
    ) -> list[RetrievedChunk]:
        """Hybrid retrieve. Filters compose with AND; None = no filter.

        Filing scope: explicit `form_type` / `latest` win; otherwise, with `infer_filing`, they are
        read from the question ("latest 10-Q", "annual report"). If the scoped search finds
        nothing, it repeats unscoped, so a wrong guess can cost ranking but never empty the answer.
        """
        qvec = "[" + ",".join(f"{v:.6f}" for v in self._embedder.embed_query(query)) + "]"

        hints = parse_filing_hints(query) if infer_filing else FilingHints()
        scope = FilingHints(
            form_type=form_type or hints.form_type,
            latest=hints.latest if latest is None else latest,
        )

        by_id, fused = self._search(query, qvec, ticker, sections, scope)
        if not fused and scope.active:
            by_id, fused = self._search(query, qvec, ticker, sections, FilingHints())
        ranked = sorted(fused.items(), key=lambda kv: kv[1][0], reverse=True)
        rerank_scores: dict[int, float] = {}
        if self._reranker is not None and ranked:
            pool = ranked[: max(self._rerank_pool, top_k)]
            scores = self._reranker.score(query, [by_id[cid][4] for cid, _ in pool])
            rerank_scores = {cid: scores[i] for i, (cid, _) in enumerate(pool)}
            ranked = [pool[i] for i in reorder(scores)]
        ranked = ranked[:top_k]

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
                    rerank_score=rerank_scores.get(cid),
                )
            )
        return out

    def _search(
        self,
        query: str,
        qvec: str,
        ticker: str | None,
        sections: list[str] | None,
        scope: FilingHints,
    ) -> tuple[
        dict[int, tuple[str, str, str, str, str, str]],
        dict[int, tuple[float, int | None, int | None]],
    ]:
        where = ["c.embedding IS NOT NULL", "c.embedding_model = %s"]
        params: list[str | list[str]] = [self._embedder.model_id]
        if ticker:
            where.append("d.ticker = %s")
            params.append(ticker.upper())
        if sections:
            where.append("c.section = ANY(%s)")
            params.append(sections)
        if scope.form_type:
            where.append("d.form_type = %s")
            params.append(scope.form_type)
        if scope.latest:
            same_form = "AND d2.form_type = %s" if scope.form_type else ""
            where.append(
                "d.filed_at = (SELECT max(d2.filed_at) FROM documents d2 "
                f"WHERE d2.ticker = d.ticker {same_form})"
            )
            if scope.form_type:
                params.append(scope.form_type)
        where_sql = " AND ".join(where)

        # websearch_to_tsquery ANDs every content word, so a natural-language question needs all
        # of them in ONE chunk and matches nothing. Postgres has already dropped the stopwords
        # and stemmed the rest; turning its ANDs into ORs keeps that normalisation (no hand-made
        # stopword list) and lets ts_rank_cd put the chunks covering the most terms first.
        tsquery = (
            "replace(websearch_to_tsquery('english', %s)::text, ' & ', ' | ')::tsquery"
            if self._keyword == "or"
            else "websearch_to_tsquery('english', %s)"
        )
        lexical_sql = f"""
            SELECT c.id, d.ticker, d.form_type, d.filed_at::date::text, c.section, c.text, d.accession
            FROM (SELECT {tsquery}) AS q(query),
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
            if self._keyword == "bm25":
                lex_rows = self._bm25_rows(cur, query, where_sql, params)
            else:
                cur.execute(lexical_sql, [query, *params])
                lex_rows = cur.fetchall()
            cur.execute(semantic_sql, [*params, qvec])
            sem_rows = cur.fetchall()

        by_id: dict[int, tuple[str, str, str, str, str, str]] = {
            r[0]: (r[1], r[2], r[3], r[4], r[5], r[6]) for r in [*lex_rows, *sem_rows]
        }
        fused = rrf_fuse([r[0] for r in lex_rows], [r[0] for r in sem_rows])
        return by_id, fused

    def _bm25_rows(
        self, cur: Any, query: str, where_sql: str, params: list[str | list[str]]
    ) -> list[tuple[Any, ...]]:
        """Keyword leg ranked by BM25. Same row shape as the SQL leg, at most POOL_PER_LEG rows.

        df is counted per query from the chunks that contain a query term (so it is always
        fresh); chunk count and mean length are cached per Retriever (they move slowly).
        """
        # `-word` means "exclude" to websearch syntax, but this leg only ever adds terms: drop such words
        # instead of scoring them positively (the semantic leg still sees the full question).
        cleaned = _NEGATED_TERM.sub(" ", query)
        cur.execute("SELECT unnest(tsvector_to_array(to_tsvector('english', %s)))", [cleaned])
        lexemes = [r[0] for r in cur.fetchall()]
        if not lexemes:
            return []
        # OR of the lexemes themselves (no round trip through websearch syntax); quotes/backslashes made safe
        any_term = " | ".join(
            "'" + lex.replace("'", "''").replace("\\", "") + "'" for lex in lexemes
        )
        cur.execute(
            """
            WITH cand AS (
                SELECT c.id, c.tsv FROM chunks c
                WHERE c.tsv @@ %s::tsquery
            ), dl AS (
                SELECT cand.id, sum(array_length(u.positions, 1)) AS n
                FROM cand, unnest(cand.tsv) u GROUP BY cand.id
            )
            SELECT cand.id, u.lexeme, array_length(u.positions, 1), dl.n
            FROM cand JOIN dl ON dl.id = cand.id, unnest(cand.tsv) u
            WHERE u.lexeme = ANY(%s)
            """,
            [any_term, lexemes],
        )
        rows: list[TermRow] = [(int(r[0]), str(r[1]), int(r[2]), int(r[3])) for r in cur.fetchall()]
        if not rows:
            return []
        df = Counter(lexeme for _id, lexeme, _tf, _dl in rows)  # one row per (chunk, lexeme)
        n_docs, avgdl = self._corpus_stats(cur)
        ranked_ids = bm25_rank(rows, df, n_docs, avgdl)
        cur.execute(
            f"""
            SELECT c.id, d.ticker, d.form_type, d.filed_at::date::text, c.section, c.text, d.accession
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE {where_sql} AND c.id = ANY(%s)
            """,
            [*params, ranked_ids],
        )
        meta = {r[0]: r for r in cur.fetchall()}
        return [meta[i] for i in ranked_ids if i in meta][:POOL_PER_LEG]

    def _corpus_stats(self, cur: Any) -> tuple[int, float]:
        if self._corpus is None:
            cur.execute(
                """
                SELECT count(*), avg(n) FROM (
                    SELECT (SELECT sum(array_length(u.positions, 1)) FROM unnest(c.tsv) u) AS n
                    FROM chunks c
                ) s
                """
            )
            row = cur.fetchone()
            self._corpus = (int(row[0]), float(row[1] or 0.0))
        return self._corpus
