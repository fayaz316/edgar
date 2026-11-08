# Status and how to resume

*Last updated 2026-11-08.* This is the public status page. Decisions and evidence live in [`adr/`](adr/); the rules each measured decision followed live in `evals/*/PROTOCOL.md` and `evals/GATE.md`.

## What exists
A cited-or-refuse RAG over Apple, JPMorgan and NVIDIA 10-K / 10-Q filings: a form-aware parser, BM25 + vector hybrid search, filing hints; a tool registry exposed over MCP; a bounded LangGraph agent with a streamed trace; an API with hashed-key auth, rate limits, a strict CSP and prompt-injection defences; a single-file UI; a calibrated independent faithfulness judge; a two-layer regression gate; 22 ADRs and a threat model; an embedder fine-tune with a leak-checked data build and a pre-registered adoption rule. Several "obvious" improvements were measured and rejected (an OR keyword leg, a reranker, an inference label).

## Verified at last check (run, not assumed)
261 tests pass, also in a clean environment without the optional embedding group (the setup CI uses); lint and strict type checks clean; frozen-evaluation-file check clean; `make eval-gate` passes (hit@8 62 of 78, MRR 0.491, no question lost); the container image builds and the app imports inside it; the first GitHub Actions run (lint, types, tests, golden validation, freeze check, image build) passed.

## Key measured numbers (small sets; each ADR states its limits)
Retrieval hit@8 62/78 over four question sets; 91% of 54 cited claims judged supported; 10/10 unanswerable questions refused; prompt-injection attacks 2/8 -> 0/8 after hardening (8 hand-written attacks, one run each); date-aware claim check 10/10 vs 5/10 on fresh claims; every-claim-cited rule: answers with an uncited claim 5/8 -> 0/8.

## Plan (decided 2026-11-08; not deployed, nothing public)
1. **Fine-tune the embedder (P5): DONE (ADR 0022).** Passed the pre-registered rule narrowly (fresh set hit@8 23 -> 26 = exactly the bar, MRR 0.497 -> 0.609; older 78 questions 62 -> 66). Offered as an opt-in `finetuned` embedder; the default stays `local` until the 440 MB weights are hosted and a new gate baseline is made.
2. A human check of ~30 judge verdicts.
3. One targeted cite-washing fix, tested on fresh data.
4. Contradiction-hunter sub-agent and a Claude Desktop MCP demo.
5. README screenshots, a one-page write-up, refreshed status.
6. Decide whether to host the fine-tuned weights and make `finetuned` the default (needs a new baseline).
**Dropped for now** (they add nothing a reviewer can check without a deployment): Secret Manager / service accounts, semantic cache, load test with SLOs, Next.js UI, demo video.

## Open items (priority order; each needs its own pre-registered spec and fresh data, because all existing evaluation sets are consumed: see `evals/golden/DECISION_LOG.md`)
1. **Cite-washing** (ADR 0020, 0021): comparison sentences can carry citations their passages do not support.
2. A human check of the judge's "supported" verdicts (the judge is same-vendor and was calibrated on claims written by the author).
3. Retrieval misses still cause the weakest answers (the fine-tune helps a little: ADR 0022).
4. **Deployment:** deliberately not done. The container has no torch, so the local embedder cannot run in it; a free route would be Cloud Run plus a free hosted Postgres with an ONNX embedder (parity to be gated).
5. Phase gaps: contradiction-hunter sub-agent; Claude Desktop connection (ADR 0012); fine-tuning; runbook, postmortem, write-up. Dropped for now: semantic cache, load test, Secret Manager / service accounts, Next.js UI, demo video; per-user identity.
6. CI gaps: the retrieval gate runs locally only (needs a hosted corpus snapshot); the dependency audit is not in CI.

## Resume
```bash
make db-up && uv run pytest && make eval-gate     # "not comparable" means the corpus changed: see evals/GATE.md
```
Run the app: the README quick start. Start any new experiment by writing its protocol and data first.
