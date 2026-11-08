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

| held-out v4 (28) | 1 | embedder fine-tune adoption (ADR 0022). Consumed: a further embedder change needs a fresh set. |

Status: golden_v0 and v1 are retired as guards. v2 has 2 uses (one more allowed), v3 has 1.
Rule for new retrieval changes: write a new held-out set (v4, new seed) first.
Seen/unseen for a decision = sets that shaped the design vs sets that did not.

## Regression gate (ADR 0016)
Runs of `make eval-gate` over all four sets are regression checks, not design decisions, so they do not count as
uses above. The baseline (`evals/baselines/retrieval_baseline.json`) was generated 2026-11-08 from the product defaults
(BM25 keyword leg, filing hints on, no reranker). Regenerating it needs an entry here.

## Injection set (ADR 0017)
`evals/injection/attacks.py` (8 attacks + criteria) was used ONCE per prompt variant to choose the default prompt (v1). It is frozen
in the manifest. A new defence needs new attacks written before it is tried; reusing these would be adaptive reuse.

## Judge (ADR 0018)
- `claims_v1` (36 claims) was used a second time: to calibrate the judge, with the judge prompt and guard frozen before the run (a decision about the judge's validity). Uses: 2.
- The 17 held-out v3 questions and 3 golden_v0 multi-step questions were used to MEASURE the agent's answer faithfulness; no design choice depends on picking among variants,
  so this is a baseline measurement, not an adaptive decision. Any future change judged on these needs a fresh set.

## L1 date change (ADR 0019)
- `claims_v2` (20 claims, new passages) was used ONCE to decide whether the date-aware L1 may replace the old one (guard in `evals/claims/L1_DATES.md`). Uses: 1. Consumed.
- The 20 answerable agent questions from the judge evaluation were re-run as a REGRESSION check (refusals and repairs before/after), not to choose between variants.

## Uncited-sentence rule (ADR 0020)
- `uncited_labeled.yaml` (74 sentences) was used once (Evaluation A) and `uncited_questions.yaml` (8 comparative questions, OFF vs ON once each) once (Evaluation B), to decide whether the rule becomes the default. Consumed.
- Afterwards two of those questions (uq5, x-001) were re-run with the rule ON and read by hand to understand the faithfulness change; that reading informed the ADR's risk section, not the adoption decision.

## Inference-label experiment (ADR 0021)
- `inference_questions.yaml` (8 comparative questions, v1 vs v2 once each) was used once. Consumed.
- The frozen injection set (`evals/injection/attacks.py`) was run against prompt v2 as a regression check: a second use, not a new design choice (it can only block adoption, not select a variant).


## Embedder fine-tune (evals/finetune/PROTOCOL.md)
- `golden_v4_heldout.yaml` (28 questions) was written and frozen BEFORE any training data existed; the control retriever was run on it once (hit@8 23/28, MRR 0.497). Frozen in the manifest on 2026-11-08. Uses for decisions: 0 so far.
- Result (2026-11-08): the fine-tuned embedder passed the pre-registered rule (v4 hit@8 23 -> 26, MRR 0.497 -> 0.609; v0..v3 62 -> 66; 4 questions lost overall). Passed narrowly: hit@8 gain equals the +3 bar. v4 uses: 1. golden_v0..v3 served as the regression check (design-exposed). The base-model gate baseline is unchanged because the product default is unchanged.

## Judge client construction (2026-11-08)
`evals/judge/judge.py` (frozen) changed in exactly two lines: the client is now built by `services.genai_client.make_genai_client` so the judge can run on Vertex AI (GCP credits) when `EA_GENAI_BACKEND=vertex`, because the free API key was rejected. The judge prompt, model name, parsing, pacing and guard are unchanged. Manifest updated deliberately. The calibration result (36/36, ADR 0018) was obtained through the API route; a judge run on the Vertex route is the same model but has not been re-calibrated, and any score from it must say so.
