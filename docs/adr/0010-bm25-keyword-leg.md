# ADR 0010 — BM25 keyword leg
Status: Accepted · Supersedes the keyword-leg part of ADR 0003 · Follows ADR 0009 · Date: 2026-11-07

## Context
ADR 0009 showed the keyword half of hybrid search was empty on natural-language questions (the AND
query matched nothing for 38 of 43 questions), and that simply ORing the terms hurt ranking because
Postgres's `ts_rank_cd` has no inverse-document-frequency: common words ("preferred stock",
"December 31, 2025") scored like rare, telling ones.

## Options considered
- **Keep the AND leg** — ineffective; hybrid in name only. Lost.
- **OR + `ts_rank_cd`** — tested, rejected by the pre-registered guard (ADR 0009).
- **BM25 over the ORed question terms** — weights terms by rarity, damps repetition and long chunks.
  Textbook constants (k1 = 1.2, b = 0.75) fixed in advance, not tuned. **Won.**
- **Weighted RRF / a reranker / a bigger candidate pool** — not tried here; separate changes that
  need their own pre-written spec and an unseen set.

## Decision
The keyword leg ranks by BM25 and its top 30 feed the same equal-weight RRF fusion as before
(`services/gateway/bm25.py`, `Retriever(keyword="bm25")`, now the default). The older "and" / "or"
modes stay selectable for before/after comparison. Specification and guard were written before any
code or run: `evals/golden/HELDOUT_PROTOCOL.md`, Addendum D.

## Evidence (each variant run once; guard applied by script)
| Set | hit@8 before -> after | MRR before -> after |
|---|---|---|
| golden_v0 (24) | 15 -> 17 | 0.368 -> 0.447 |
| held-out v1 (19) | 17 -> 17 | 0.660 -> 0.634 |
| held-out v2 (18) | 10 -> 16 | 0.303 -> 0.446 |
| combined (61) | 42 -> 50 | 0.440 -> 0.505 |

Guard passed on all three conditions. 24 questions improved and 10 got worse (two-sided sign test
p about 0.02). Lenient scores moved the same way (see the result files).

## Consequences
- **Good:** the keyword leg now contributes on natural-language questions, and the largest gain
  appeared on the paraphrased held-out set (v2), the one closest to real use.
- **Bad / unknowns:**
  - v1 (questions that echo the source wording) did not improve: MRR -0.026, hit@1 0.579 -> 0.474.
    Wording-matched questions may be served slightly worse; this is a small, within-guard cost.
  - Still 11 of 61 questions miss entirely; none of the v2 misses has been diagnosed.
  - Not verified: the full `/ask` path end to end (needs the generation key); behaviour on a
    corpus much larger than 4.9k chunks. Per query, the candidate step reads every chunk that
    contains any query term, and corpus size and mean chunk length are cached per process, so they
    go stale after a re-ingest until restart. A stats table and an index would be needed at scale.
  - Retrieval is still tuned only against 61 questions; effects under about 2 points are invisible.
- **Consumed data:** all three sets have now informed decisions. The next retrieval change needs a
  fresh held-out set (v3) first.
- **Revisit trigger:** a larger or real-usage golden set shows BM25 losing to the control; or the
  corpus grows enough to make the candidate query slow.
