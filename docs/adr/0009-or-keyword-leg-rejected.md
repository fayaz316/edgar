# ADR 0009 — OR-ing the keyword leg: a real bug found, the obvious fix rejected
Status: Accepted (decision: do not adopt; the real fix is ADR 0010) · Amends ADR 0003 · Date: 2026-11-07

## Context
ADR 0003 describes hybrid retrieval: keyword (Postgres FTS) + vectors, fused by RRF. Measured, the
keyword leg is dead on natural-language questions: `websearch_to_tsquery` ANDs every content word,
so a chunk must contain all of them.

| Set | Questions where the keyword leg returns zero chunks |
|---|---|
| golden_v0 | 24 of 24 |
| held-out v1 | 14 of 19 |

So "hybrid" retrieval has really been embedding-only on 38 of 43 questions. This was found while
diagnosing misses, not by the eval score.

## Options considered
- **OR the question's terms** — take Postgres's own normalised query (stopwords already dropped,
  words stemmed) and turn `&` into `|`, ranked by `ts_rank_cd`. No hand-made stopword list, no
  weights. Implemented as `Retriever(lexical_any=True)`. **Tested, rejected.**
- **IDF-aware keyword scoring (BM25-like)** — the likely right fix; Postgres has no built-in
  BM25. Not tried: any variant tuned now would be tuned on data already used for this decision.
- **Leave it and document it** — **Won**, for now.

## Decision
Keep the keyword leg as AND (`lexical_any=False`, the default). Keep the OR path in code,
off by default, so the comparison can be re-run.

The decision rule was written **before** measuring (`evals/golden/HELDOUT_PROTOCOL.md`): adopt on
mechanism, reject if the combined set loses more than 2 strict hit@8 questions or 0.03 MRR.

## Evidence (each run once; same embedder, hints ON)
| Set | hit@1 AND / OR | hit@8 AND / OR | MRR AND / OR |
|---|---|---|---|
| golden_v0 (24) | 0.250 / 0.250 | 0.625 / 0.625 | 0.368 / 0.372 |
| held-out v1 (19) | 0.579 / 0.368 | 0.895 / 0.789 | 0.660 / 0.518 |
| combined (43) | | 32 / 30 questions | 0.497 / 0.437 |

MRR fell 0.060 (limit 0.030) => rejected. On golden_v0 the OR leg changed nothing measurable.

Why it hurts, from one inspected case (`h-jpm-10k-004`): the OR leg did rank the right chunk 3rd, but
also surfaced many generic chunks that match common words ("preferred stock", "December 31,
2025") with similar scores. Fused with equal weight, they pushed the right chunk out of the top 8.
That is a single example, not a proven general cause.

## Consequences
- **Bad (accepted):** retrieval stays embedding-only in practice; ADR 0003's "hybrid" claim is
  not true in effect until the keyword leg is fixed.
- **Caveat on the held-out set:** its questions were written from the chunk text, so they echo
  the source wording and score higher (control hit@8 0.895) than golden_v0 (0.625). It is
  easier than real use, and it has now been used for one decision.
- **Next step, not done:** build a second held-out sample (new seed) before trying an IDF-aware
  keyword score, and judge that change on it only. Weighting RRF legs is an alternative to try
  under the same rule.
