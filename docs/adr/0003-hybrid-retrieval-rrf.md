# ADR 0003 — Hybrid retrieval: Postgres full-text + pgvector, fused with RRF
Status: Accepted (retroactive — written after the code; decision made in Phase 1) · Date: 2026-11-07

## Context
Analysts ask two kinds of questions. Some hinge on **exact terms** ("Item 1A", a product
name, "Compute & Networking"); others are **paraphrases** ("worries about demand
concentration" vs. the filing's "customer concentration"). Embeddings alone blur exact
terms; keyword search alone misses paraphrase. Budget is tiny and we want one database.

## Options considered
- **Vector search only** — simplest, but weak on exact identifiers and numbers. Lost.
- **Managed vector DB (Pinecone etc.)** — strong, but a second datastore, a bill, and data
  leaving our boundary. Lost on cost and surface area.
- **Postgres `tsvector` + `pgvector` in one DB, fuse the two ranked lists** — one system,
  free locally, same schema on Cloud SQL. **Won.**
- Fusion method: **Reciprocal Rank Fusion (RRF, k=60)** over *weighted score blending*.
  RRF uses only rank positions, so we never calibrate `ts_rank` against cosine distance —
  two scales that are not comparable.

## Decision
Retrieve the top 30 from each leg (lexical `ts_rank_cd`, semantic cosine via HNSW), fuse
with RRF, return the top *k*. Embeddings: `gemini-embedding-001`, 768 dims.

## Consequences
- ✅ One datastore, one backup story, one place to filter (ticker, section).
- ⚠️ `ts_rank_cd` is **not BM25** (earlier notes call it "BM25-grade"; that overstated it —
  Postgres ranks by term frequency and cover density, with no inverse-document-frequency
  weighting). Fine for now; revisit if lexical-only recall looks weak.
- ⚠️ `websearch_to_tsquery` has **AND semantics**: every query term must appear in a
  passage, so the lexical leg is often empty for long natural-language questions. RRF
  degrades gracefully to semantic-only. OR-expansion is deferred until the golden set shows
  it matters ("measure, then optimize").
- ⚠️ Filtered HNSW queries can return fewer than *k* rows (the index is searched, then
  filtered). Fine at ~4.5K chunks; revisit with pgvector iterative scans at scale.
- ❌ No reranker yet — the Phase 1 exit criterion lists one. Build it or amend the criterion.
- **Revisit trigger:** `make eval-retrieval` hit@5 below target, or lexical-leg-empty rate
  high on golden questions.
