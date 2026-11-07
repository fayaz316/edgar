# ADR 0002 — Local-first Postgres (Docker pgvector), Cloud SQL for the demo phase

Status: Accepted · Supersedes: ADR 0001 decision #2 ("Supabase free (dev)")

## Context
Phase 1 needs Postgres with pgvector and full-text search for hybrid retrieval. ADR 0001
planned Supabase for dev. Two things changed: (a) a standing supply-chain policy — only
verified sources (official Docker images, pinned lockfiles) — and (b) the requirement
that the *same schema* promote unchanged to the production database.

## Decision
1. Dev: `pgvector/pgvector:pg17` (image published by the pgvector project) in Docker,
   bound to **127.0.0.1:5433 only**, named volume, password in the gitignored `.env`.
2. Demo/prod: smallest Cloud SQL Postgres, created only for the demo phase and covered by
   `make teardown`. Schema (`db/schema.sql`) is identical in both.
3. No managed third-party database in the dev loop.

## Consequences
- Zero cost and zero third-party data egress while iterating; works offline.
- "Local → Cloud SQL" is the standard local-to-managed promotion path and is itself testable.
- Dev data lives in a Docker volume: it is disposable by design — everything is
  reproducible from the raw-HTML cache (`data/raw/`) plus `make reingest` (unchanged
  chunk embeddings are reused, so re-ingesting costs no embedding quota).
- ADR 0001 decision #2 is void; decisions #1 and #3 stand.
