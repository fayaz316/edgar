# ADR 0022 — Fine-tuned embedder: passes the pre-registered rule narrowly; offered as an opt-in provider, default unchanged
Status: Accepted · Date: 2026-11-08 · Protocol (written before any data): `evals/finetune/PROTOCOL.md` · Result: `evals/finetune/decision.json`

## Context
Retrieval misses cause the weakest answers (about 1 question in 5 misses its evidence in the top 8). Three earlier "obvious" fixes were measured and rejected.
This one trains the embedder (BAAI/bge-base-en-v1.5) on 2,664 machine-written question / passage / hard-negative triples built from the filings.

## What was controlled
- **Leakage:** every chunk that is evidence for any evaluation question, its neighbours, v4 candidates and every near-duplicate (5-word shingle Jaccard >= 0.5) were excluded from training and from negatives; a script asserts it (890 of 4,867 chunks excluded).
- **Fresh exam:** `golden_v4_heldout.yaml` (28 questions) was written and frozen before any training pair existed; its control score was recorded first (23/28, MRR 0.497).
- **One run, fixed settings, rule applied by script** (`evals/finetune/decide.py`): v4 MRR +0.05 and hit@8 +3; no regression on the 78 older questions; at most 5 questions lost overall.

## Result (control = base model, candidate = fine-tuned; each run once, strict scoring, k = 8)
| Set | hit@8 | MRR |
|---|---|---|
| v4 (fresh, 28) | 23 -> 26 | 0.497 -> 0.609 |
| v0..v3 combined (78) | 62 -> 66 | 0.491 -> 0.545 |
Questions that moved into the top 8: 11; out of it: 4 (v4: 4 gained, 1 lost). Rank improved on 38 questions and worsened on 19.
By company (all 106 questions): NVIDIA hit@8 33 -> 37, MRR 0.495 -> 0.619; JPMorgan 27 -> 28, 0.518 -> 0.592; Apple 25 -> 27, MRR 0.496 -> 0.490 (flat).
The rule returned ADOPT. Training: one L4 spot GPU, 69 seconds, loss 2.21 -> 0.79, validation loss 0.44.

## Decision
The model passed the bar that was fixed in advance, so it is kept: the `finetuned` embedder (`EA_EMBEDDER=finetuned`, `EA_FT_MODEL_PATH=<checkpoint dir>`) is a supported provider and the recommended one.
The product DEFAULT stays `local` for now, because the 440 MB weights are not in the repository and a default nobody can reproduce would break the quick start and the CI gate baseline.
Switching the default needs: weights hosted somewhere downloadable, a regenerated gate baseline for the new embedder, and a re-embedded corpus (see PROTOCOL.md).

## Why this is weaker evidence than it looks
- The hit@8 bar was +3 and the result is exactly +3: one different question would have meant REJECT. MRR (+0.11 on v4) is the steadier signal.
- Pooled over all five sets the gains outnumber the losses 11 to 4 (one-sided sign test p = 0.059, not below 0.05). Suggestive, not conclusive. 106 questions, written by the author.
- The 78 older questions are design-exposed (they shaped earlier decisions); only v4 is a fresh exam.
- Same companies and filings in training and test: this shows better ranking of unseen passages, not generalisation to new companies. Apple's MRR did not improve.
- Training questions were written by Gemini; v4 questions were written separately, under the anti-echo rule. That separates the styles but does not make either independent of the models used elsewhere.
- Library versions differed slightly between training (transformers 5.20.2, Python 3.10) and local embedding (5.22.2, Python 3.12); the weights are what is scored, not the library.

## Consequences
- v4 is consumed for this decision (DECISION_LOG). A further embedder change needs a new fresh set.
- The 5 old misses on v4 were never diagnosed; 4 of them now hit, which was not designed for.
- Cost: about 25 minutes of one spot GPU VM plus a few cents of Gemini calls, against the GCP free-trial credits. The VM and its disk were deleted afterwards (verified).
