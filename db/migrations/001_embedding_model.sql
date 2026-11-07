-- Migration 001: tag every vector with the model that produced it.
--
-- Why: vectors from different embedding models are not comparable. Without a tag, switching
-- models would silently mix incomparable vectors and retrieval would return nonsense that
-- still "looks" like results. With the tag, retrieval filters to the active model and the
-- backfill re-embeds anything tagged otherwise.
--
-- Run:  make db-migrate     (idempotent; STOP any running `make embed` first — an old
-- backfill writes vectors without a tag, which the constraint below rejects)

BEGIN;

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding_model TEXT;

-- everything embedded so far came from Gemini at 768 dims
UPDATE chunks
SET embedding_model = 'gemini-embedding-001@768'
WHERE embedding IS NOT NULL AND embedding_model IS NULL;

CREATE INDEX IF NOT EXISTS chunks_model_idx ON chunks (embedding_model);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chunks_vector_has_model'
    ) THEN
        ALTER TABLE chunks
            ADD CONSTRAINT chunks_vector_has_model
            CHECK ((embedding IS NULL) = (embedding_model IS NULL));
    END IF;
END $$;

COMMIT;
