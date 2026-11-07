# ADR 0016 — A two-layer eval gate: offline in CI, full retrieval gate locally
Status: Accepted · Date: 2026-11-08

## Context
Every retrieval and agent change so far was judged by experiments run by hand. Nothing stopped a later change from
quietly making retrieval worse, or the frozen question sets from being edited to make a change look better. The
project plan's Phase 3 asks for evals that block regressions on every pull request. GitHub's runners have no Postgres,
no corpus and no 440 MB embedding model, so a full retrieval eval cannot simply run there.

## Options considered
- **Two layers: an offline gate that CI enforces, plus a full retrieval gate that runs where the corpus lives
  (`make eval-gate`).** **Won**, because both can be verified today.
- **Full gate in GitHub Actions** — needs a hosted corpus snapshot (the SEC data plus embeddings, about 15 MB
  compressed) and a model cache. Right end state; not built, because it could not be tested from here.
- **Commit results files and check them in CI** — trivially gameable: whoever changes the code also writes the
  results. Lost.
- **An LLM-judge gate** — needs an independent faithfulness judge that does not exist yet (ADR 0014). Deferred.

## Decision
Rules were written before the gate existed (`evals/GATE.md`).
- **Layer 1 (CI, every pull request, no external services):** a hash manifest of the frozen evaluation files
  (`evals/freeze.py`; a test and a CI step fail if any frozen file changes); the claim-check L1 contract test (false
  flags <= 10%, changed-number detection >= 90%); the gate logic's unit tests; a test that pins the product defaults
  the gate protects.
- **Layer 2 (`make eval-gate`, local/pre-push):** run the product-default retriever over all four question sets, compare
  per-question results with a committed baseline (`evals/baselines/retrieval_baseline.json`). FAIL on a combined MRR
  drop > 0.02, a combined hit@8 drop > 1 question, a single set losing > 2 hit@8 questions or > 0.05 MRR, or more than 4
  negative flips (a question answered before that now misses). ERROR, not pass, if the corpus fingerprint, embedder,
  settings or golden-file hashes differ from the baseline, so a changed corpus cannot masquerade as a regression or a pass.
- The eval runner now uses the retriever's own defaults, so the gate tests what the product actually does.

## Evidence (each check was exercised, not assumed)
- **Determinism:** the baseline was generated once, then the gate was run again on the same code and corpus: identical
  results, zero flips, PASS (hit@8 62 of 78, MRR 0.489).
- **It catches breakage:** shrinking the candidate pool from 30 to 3 per leg made the gate FAIL (exit code 1) with
  "combined hit@8 fell 62 -> 59" and "6 negative flips", naming the six lost questions. Notably MRR ROSE (0.489 -> 0.536)
  while recall fell: an MRR-only gate would have approved that change (the same pattern as the reranker, ADR 0011).
  The line was restored and the gate passes again.
- **It catches tampering:** editing one word of a frozen question set made the freeze check fail; restored.
- **Unit tests:** 13 tests for the gate logic (including realistic set sizes and the not-comparable cases), the default-pinning test,
  and the claim-check contract test. 180 tests pass in total.

## Consequences
- **Layer 2 is not in GitHub Actions.** CI enforces only layer 1; a regression in retrieval quality is caught by whoever runs
  `make verify` before pushing. Closing this needs a hosted corpus snapshot.
- **The baseline is trusted, not proven:** a person can regenerate it after a regression. The mitigation is process (a
  baseline change needs an ADR or DECISION_LOG entry and shows up in review), not code.
- **Small sets, small margins:** 78 questions; the margins catch obvious breakage, not subtle drift. They are not
  adoption criteria (those stay in HELDOUT_PROTOCOL.md).
- **Any re-ingest changes the corpus fingerprint** and needs a deliberate baseline regeneration; until then the gate
  reports ERROR rather than a verdict.
- **Retrieval only:** nothing here gates answer quality or faithfulness.
- **Revisit trigger:** a hosted corpus snapshot exists (then move layer 2 into CI), or an independent faithfulness judge
  exists (then add an answer-quality gate).
