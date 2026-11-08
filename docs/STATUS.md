# Status and how to resume

*Last updated 2026-11-08.* This is the public status page. Decisions and evidence live in [`adr/`](adr/); the rules each measured decision followed live in `evals/*/PROTOCOL.md` and `evals/GATE.md`.

## What exists
A cited-or-refuse RAG over Apple, JPMorgan and NVIDIA 10-K / 10-Q filings: a form-aware parser, BM25 + vector hybrid search, filing hints; a tool registry exposed over MCP; a bounded LangGraph agent with a streamed trace; an API with hashed-key auth, rate limits, a strict CSP and prompt-injection defences; a single-file UI; a calibrated independent faithfulness judge; a two-layer regression gate; 21 ADRs and a threat model. Several "obvious" improvements were measured and rejected (an OR keyword leg, a reranker, an inference label).

## Verified at last check (run, not assumed)
260 tests pass, also in a clean environment without the optional embedding group (the setup CI uses); lint and strict type checks clean; frozen-evaluation-file check clean; `make eval-gate` passes (hit@8 62 of 78, MRR 0.491, no question lost); the container image builds and the app imports inside it.

## Key measured numbers (small sets; each ADR states its limits)
Retrieval hit@8 62/78 over four question sets; 91% of 54 cited claims judged supported; 10/10 unanswerable questions refused; prompt-injection attacks 2/8 -> 0/8 after hardening (8 hand-written attacks, one run each); date-aware claim check 10/10 vs 5/10 on fresh claims; every-claim-cited rule: answers with an uncited claim 5/8 -> 0/8.

## Open items (priority order; each needs its own pre-registered spec and fresh data, because all existing evaluation sets are consumed: see `evals/golden/DECISION_LOG.md`)
1. **Cite-washing** (ADR 0020, 0021): comparison sentences can carry citations their passages do not support.
2. A human check of the judge's "supported" verdicts (the judge is same-vendor and was calibrated on claims written by the author).
3. Retrieval misses still cause the weakest answers.
4. **Deployment:** not deployed. The container has no torch, so the local embedder cannot run in it yet.
5. Phase gaps: contradiction-hunter sub-agent; Claude Desktop connection (ADR 0012); semantic cache; load test with SLOs; Secret Manager / service accounts; per-user identity; Next.js UI and demo video; fine-tuning; runbook, postmortem, write-up.
6. CI gaps: the retrieval gate runs locally only (needs a hosted corpus snapshot); the dependency audit is not in CI.

## Resume
```bash
make db-up && uv run pytest && make eval-gate     # "not comparable" means the corpus changed: see evals/GATE.md
```
Run the app: the README quick start. Start any new experiment by writing its protocol and data first.
