-- Edgar Analyst schema v1 — Phase 1
--
-- Design notes (the WHY):
-- * documents = one SEC filing (natural key: ticker + accession number).
-- * chunks    = structure-aware passages (by filing SECTION, not fixed-size
--   windows) — chunking strategy is half of RAG quality.
-- * tsv       = lexical search column (Postgres full-text search; BM25-grade
--   ranking via ts_rank). Combined with vector search = hybrid retrieval.
-- * embedding = Gemini text-embedding (768 dims). Nullable until Phase 1b —
--   schema lands before the embedder exists (migrations precede code).
-- * HNSW over IVFFlat: no training step, better recall/latency at our scale.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ticker     TEXT NOT NULL,
    form_type  TEXT NOT NULL CHECK (form_type IN ('10-K', '10-Q', '8-K')),
    accession  TEXT NOT NULL,
    period_end DATE,
    filed_at   TIMESTAMPTZ NOT NULL,
    uri        TEXT NOT NULL,
    UNIQUE (ticker, accession)
);

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    section     TEXT NOT NULL,
    seq         INT NOT NULL,
    text        TEXT NOT NULL,
    tsv         TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    embedding   vector(768),
    embedding_model TEXT,  -- which model made `embedding`; vectors from different models are not comparable
    UNIQUE (document_id, section, seq),
    CONSTRAINT chunks_vector_has_model CHECK ((embedding IS NULL) = (embedding_model IS NULL))
);

CREATE INDEX IF NOT EXISTS chunks_tsv_idx       ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_doc_idx       ON chunks (document_id);
CREATE INDEX IF NOT EXISTS chunks_model_idx     ON chunks (embedding_model);
CREATE INDEX IF NOT EXISTS documents_ticker_idx ON documents (ticker, filed_at DESC);
