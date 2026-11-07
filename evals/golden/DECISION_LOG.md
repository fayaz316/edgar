# Decision log: how often each evaluation set has informed a decision

Why: a test set that has guided several choices is no longer an independent test of the next one
(adaptive reuse). Each use below is a place where the set's results influenced a design decision, or
where its misses were read. A set used 3 or more times is retired as a GUARD for new decisions; its
numbers are still reported, but a new change needs a fresh set.

| Set | Uses | Decisions it informed |
|---|---|---|
| golden_v0 (24) | 5 | miss diagnosis (0007/0008); filing hints designed from its misses (0008); OR keyword leg (0009); BM25 (0010); reranker (0011) |
| held-out v1 (19) | 4 | OR keyword leg (0009); filing hints check (0008); BM25 (0010); reranker (0011) |
| held-out v2 (18) | 2 | BM25 (0010); reranker (0011) |
| held-out v3 (17) | 1 | reranker (0011) |
| claims_v1 (36) | 1 | claim-level checker: L1 enforced, L2 rejected (ADR 0014). Consumed: a new checker variant needs claims_v2. |

Status: golden_v0 and v1 are retired as guards. v2 has 2 uses (one more allowed), v3 has 1.
Rule for new retrieval changes: write a new held-out set (v4, new seed) first.
Seen/unseen for a decision = sets that shaped the design vs sets that did not.
