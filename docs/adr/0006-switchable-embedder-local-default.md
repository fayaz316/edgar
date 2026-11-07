# ADR 0006 — Switchable embedder; local Hugging Face model as the default
Status: Accepted · Date: 2026-11-07

## Context
The Gemini free tier throttled the corpus backfill to ~24 chunks/minute (batches of 50 were
rejected with 429; the job halved itself to 25). Re-embedding after the parser change would
take ~3.4 hours, and every future parser/chunking experiment would pay that again. The
embedding model also decides data-residency (does filing text leave the machine?) and cost.

## Options considered
- **Keep Gemini free tier** — €0 but slow and quota-fragile; the eval loop becomes hours.
- **Gemini paid tier** — fast, about $0.20–0.25 for this corpus at $0.15 per 1M tokens, but
  needs billing on the API and still sends text off-machine.
- **Local open model (`BAAI/bge-base-en-v1.5`, MIT, 768 dims, 512-token limit)** — free,
  no quota, minutes not hours, no data egress. Possibly slightly weaker retrieval than
  Gemini; we measure that rather than assume it.
- **Hard-code one provider** — fastest to write, but makes the next switch a rewrite.

## Decision
1. All callers use a small `Embedder` interface (`services/embeddings.py`); providers are
   `local` (default) and `gemini`, chosen by `EA_EMBEDDER` / `make ... EMBEDDER=`.
2. **Every vector is tagged with its model** (`chunks.embedding_model`, with a CHECK that
   vector and tag exist together). Retrieval filters to the active model; the backfill
   re-embeds anything tagged otherwise. Vectors from different models are never mixed.
3. The local model is pinned by git revision, loaded from safetensors with
   `trust_remote_code=False`, from the optional dependency group `local-embed` (so CI and
   the gateway image don't carry `torch` unless they opt in).
4. Choose between models with the retrieval eval on the same golden questions, not by taste.

## Consequences
- ✅ Eval loop in minutes; no quota walls; filings never leave the machine.
- ✅ Switching or A/B-ing models is a flag, and the tag makes mix-ups impossible rather
  than merely unlikely. The gateway refuses to start if no chunk matches its model.
- ⚠️ Switching models means re-embedding the corpus (cheap locally; hours on the free tier).
- ⚠️ bge truncates input at 512 tokens; our chunks are ~1,200 characters (~300 tokens), but
  very long table rows could be cut. Watch for it in the parse report.
- ⚠️ Shipping the gateway to Cloud Run with the local model means a larger image (`torch`)
  and slower cold starts. Decide at deployment: ONNX runtime, or Gemini for serving.
- ⚠️ Query-time prefix matters: bge expects an instruction on queries and none on passages;
  getting that wrong degrades recall silently. It is covered by a unit test.
- **Revisit trigger:** if `local` hit@5 is clearly below `gemini` on the golden set, rerun
  that comparison on the paid tier and decide on evidence.
