# ADR 0011 — Cross-encoder reranker: built, measured, not adopted
Status: Accepted (decision: keep off by default) · Amends the Phase-1 exit criterion · Date: 2026-11-07

## Context
The project plan's Phase 1 asks for "hybrid search + rerank". After ADR 0010 the first stage finds the
target in its top 30 for most questions; a reranker could reorder those 30 better than rank-position
fusion. Specification and guard were written before any code or run (HELDOUT_PROTOCOL.md, Addendum G),
with a new unseen held-out set (v3) for an independent check.

## Options considered
- **Cross-encoder `cross-encoder/ms-marco-MiniLM-L-6-v2`** (about 90 MB, CPU, Apache-2.0) over the top
  30 fused chunks, text only, no score blending. **Built and tested; fixed in advance.**
- **A larger reranker (e.g. a bge-reranker model, about 1 GB)** — plausibly better; not tried. It needs
  its own written spec and an unseen set (v4), so it cannot be a quiet re-run after this result.
- **LLM reranking via Gemini** — spends the free generation quota on retrieval. Lost.
- **No reranker** — **Won**, by the guard.

## Decision
Keep the reranker in the code as an opt-in flag (`Retriever(reranker=CrossEncoderReranker())`,
`--rerank` in the eval). The default pipeline has no reranker. The Phase-1 criterion "rerank" is
therefore amended: implemented and measured, not enabled, because it did not pass its guard.

## Evidence (each run once; guard applied by script)
| Set | hit@8 before -> after | MRR before -> after |
|---|---|---|
| golden_v0 (24) | 17 -> 14 | 0.447 -> 0.440 |
| held-out v1 (19) | 17 -> 17 | 0.634 -> 0.709 |
| held-out v2 (18) | 16 -> 14 | 0.446 -> 0.539 |
| held-out v3 (17, unseen) | 12 -> 14 | 0.430 -> 0.492 |
| combined (78) | 62 -> 59 | 0.489 -> 0.540 |

It improves ordering (MRR +0.051, more first-place hits) but loses recall (hit@8 62 -> 59). Failed
conditions: golden_v0 lost 3 hit@8 questions (limit 2), and combined hit@8 fell. Latency was fine, about
0.2 s per question on CPU.

## Consequences
- **Bad (accepted):** no rerank step in the default path; ordering gains are left on the table.
- **Hypothesis, untested:** a model trained on web-search queries (MS MARCO) may judge dense financial
  filing text poorly and sometimes demote the right chunk. Not verified; no misses were diagnosed.
- **Mixed picture worth remembering:** MRR rose on 3 of 4 sets while recall fell on 2; whether ordering
  or recall matters more depends on the consumer (a human reading the top hit vs an agent reading
  all 8). The guard chose recall; the later agent phase may justify revisiting.
- **Revisit trigger:** the agent loop (Phase 2) turns out to read only the top few results, or a larger
  reranker is specified and tested on a fresh set (v4).
