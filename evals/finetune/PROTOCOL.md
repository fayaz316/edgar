# Embedder fine-tune (P5) — protocol, written BEFORE any training data, sampling or measurement

Date written: 2026-11-08. Do not edit this section afterwards; later changes go in dated addenda at the bottom.

## Question
Does fine-tuning the retrieval embedder (BAAI/bge-base-en-v1.5) on question/passage pairs built from the
filings improve retrieval on questions it was not tuned against? "Obvious" improvements have already failed
here three times (OR keyword leg, reranker, inference label), so the default outcome is **not adopted**.

## Why this can mislead us (and the controls)
1. **Eval passages leaking into training.** All 11 filings are cited by some evaluation set, so we cannot hold out
   whole filings. Instead, a script builds an *exclusion set* and training pairs are drawn only from outside it:
   - every chunk that is expected evidence of ANY question in golden_v0..v4 (anchor `snippet_hint` found in the chunk);
   - the chunk's neighbours (same document and section, `seq` ± 1);
   - every chunk sampled as a v4 candidate (used or skipped);
   - every chunk (any document) with 5-word-shingle Jaccard >= 0.5 against an excluded chunk (10-Qs repeat text).
   The script asserts that no training chunk is in the exclusion set and writes counts + a hash to
   `evals/finetune/training_manifest.json`. A failed assertion stops the run.
2. **Adaptive reuse.** golden_v0..v3 are consumed (DECISION_LOG), so they act only as a regression check. The
   adoption test is a **fresh set, golden_v4_heldout.yaml**, authored and frozen before any training pair exists.
3. **Question-style overfitting.** Training questions are machine-written; v4 questions are written separately
   (not by the Gemini generator) under the anti-echo rule, so the style differs.
4. **Peeking.** One training run, hyperparameters fixed below, no checkpoint selection, no sweeps.

## Fresh set v4 (built first)
Same rules as HELDOUT_PROTOCOL.md (Addendum B/F) with: seed `md5(c.id::text || 'heldout-v4')`; 6 candidates per
(ticker, form_type) (36 total), length 500-1500 chars; excluded from sampling: every evidence chunk of v0..v3 and
every skipped chunk id listed in their headers. Skips only for `boilerplate`, `table-fragment`,
`no-standalone-question`, each recorded in the YAML header. Anti-echo: no 4-word run shared between a question and
its anchor, checked mechanically before any search. The control retriever (current product defaults) is run on v4
ONCE; v4 is then frozen in the manifest and never edited.

## Training data (generated after v4 is frozen)
- Eligible chunks: 300-2000 chars, digit fraction <= 0.30, >= 40 words, not in the exclusion set.
- Questions: `gemini-3.1-flash-lite` (existing adapter; API or Vertex, same model, same prompt), 2 questions per chunk
  from the chunk text alone: (a) a direct question, (b) a paraphrase sharing no 4-word run with the chunk
  (mechanical check; failures dropped, not retried). Prompt text is committed with the generated file.
- At most 3,000 pairs. Hard negative per pair: from the base model's ranking, a chunk at rank 10-40 that is not in the
  same document + section as the positive and not a near-duplicate (Jaccard >= 0.5) of it.
- Split: 5% of CHUNKS (not pairs), seeded, used only to confirm the loss decreases; never to pick a checkpoint.

## Training (fixed now)
Base model at the pinned revision in `services/embeddings.py`; sentence-transformers
`MultipleNegativesRankingLoss` (in-batch negatives + the hard negative); queries get the bge query prefix, passages none;
learning rate 1e-5, warmup 10%, batch size 32, 1 epoch, max sequence length 512, fp16, seed 42. The final weights of
that single run are the candidate. An infrastructure failure (spot preemption, OOM) may be re-run with the identical
config and is logged; a bad *result* may not be.
Compute: one spot GPU VM (L4 or T4, europe-west4), wall-clock limit 2 hours, VM and disks deleted afterwards,
step budget EUR 15 of GCP credits. Weights stay out of git; `training_manifest.json`, the loss log and the weights'
SHA-256 are committed. Model tag: `edgar-ft-bge-base@<sha8>`.

## Measurement
Candidate vs control (both full re-embedded corpora, same chunks, same retriever defaults, k = 8) in a scratch
database, strict scoring, one run each:
- v4 (primary, fresh);
- golden_v0..v3 (78 questions; regression check, also not training data but design-exposed).
Needs a comparison mode in the gate (the current gate returns ERROR for a different embedder or fingerprint).
It must compare per-question results and require the identical chunk-text fingerprint; it is built and unit-tested
before the candidate is scored.

## Decision rule (pre-registered)
ADOPT only if ALL hold:
1. v4 strict MRR improves by >= 0.05 and strict hit@8 improves by >= 3 questions;
2. on v0..v3 combined the GATE.md regression rules pass (MRR no worse than -0.02, hit@8 no worse than -1, no single
   set worse than -2 hit@8 / -0.05 MRR);
3. total negative flips (control hit@8, candidate miss) across v0..v4 are <= 5.
Otherwise REJECT and keep the default. Whatever happens is recorded as ADR 0022 and a DECISION_LOG entry, with per-company
results, wins/losses per question, and the caveats below. An adopted model also needs a new baseline file (deliberate) and a
note on how the image would carry it (not deployed, so documentation only).

## Honest limits
- v4 has ~30 questions: only a large effect is visible; passing is "suggestive", failing is "no evidence of benefit".
- Training and test come from the same companies and filings; this tests unseen *passages*, not unseen companies.
- The v4 questions have not been checked by a second person.
- Gemini writes the training questions; the generation model may share biases with our answerer.
- Re-embedding invalidates the existing baseline; the control is re-run on the same scratch database for fairness.

## Addendum A — v4 written, frozen, control run recorded once (2026-11-08; the rules above are unchanged)
- `evals/golden/golden_v4_heldout.yaml`: 28 questions (19 grounded, 9 numeric) from 36 sampled chunks, 8 skipped with reasons
  in its header. Anti-echo check: 0 failures. Schema/integrity validation passes. Frozen in the manifest.
- Control (product defaults, local bge, k = 8), strict: hit@1 0.357, hit@3 0.571, hit@5 0.679, **hit@8 0.821 (23/28)**, **MRR 0.497**.
  Lenient hit@8 0.929, MRR 0.686. Misses: hd-aapl-10k-001, hd-aapl-10q-005, hd-jpm-10q-001, hd-nvda-10k-004, hd-nvda-10k-006.
  The misses are NOT diagnosed, on purpose (reading why they fail is the first step toward tuning to them).
- Consequence for the decision rule, stated now and not acted on: only 5 questions can improve at hit@8, so "hit@8 +3" needs 3 of
  those 5 to flip, and any loss elsewhere counts against it. The rule is kept as written; a failure here may reflect little headroom,
  and the write-up must say so rather than loosen the rule afterwards.
- Cost of freezing: the manifest gained one entry. v4 is deliberately NOT part of the regression gate yet (adding it would change
  the baseline's set list); it joins the gate only if a candidate is adopted.

## Addendum B — implementation details fixed before any training question exists (2026-11-08; no rule above changes)
- Exclusion result (`eligible_manifest.json`): 4,867 chunks, 890 excluded (evidence, neighbours, skipped ids, near-duplicates), 3,889
  eligible; the leak assertion passed. JPMorgan has 66% of the eligible chunks.
- Sampling: instead of a random draw, 1,500 chunks are taken by water-filling across the 11 filings (small filings give everything,
  the rest are capped equally) so the training mix is not 66% JPMorgan. Order inside a filing: md5 of the chunk id with a fixed salt.
- Questions: model `gemini-3.1-flash-lite`, prompt committed in `generate_questions.py`; the model may answer null for a chunk with
  no standalone content (cover page, table of contents, bare table). Paraphrase questions sharing a 4-word run with the chunk are dropped.
- Hard negatives are chosen only among ELIGIBLE chunks (never an evaluation passage, even as a negative), rank 10-40 of the base
  model, not in the positive's document + section, not a near-duplicate of the positive. Max 3,000 pairs.
- Training: `NO_DUPLICATES` batch sampler so two questions about one chunk are never each other's in-batch negatives; all other
  hyperparameters as above. The validation split (5% of chunks) is used only to see that the loss behaves.
- Scoring of the candidate: `evals/finetune/decide.py` applies the decision rule mechanically to the control and candidate result
  directories (unit-tested; it refuses to compare different corpora or configs).
- Provider: the candidate is scored through a new `finetuned` embedder (`EA_FT_MODEL_PATH` points at the checkpoint; the vector tag
  comes from the weights' SHA-256), in a scratch database so the main corpus and its baseline stay untouched.

## Addendum C — generator prompt revised once, before the full run (2026-11-08)
The first 8 probe outputs (chunks 4599-4606, all from filings' ordinary text; no evaluation question involved) showed paraphrases
that dropped the company name ("the firm") and one that invented a detail ("third week of August"). Training labels like that are
noisy, so the prompt was tightened ONCE: both questions must name the company, and dates/periods/numbers must stay exact.
The same 8 chunks were re-run to confirm (company named, dates exact). No other change; the model, sample and rules are as above.
Generation runs through Vertex AI (`--vertex`, billed to GCP credits) because the free API key was rejected.

## Addendum D — training data built (2026-11-08, before any training)
1,500 chunks were sent to the generator (two network retries; no chunk skipped): 2,843 questions kept (1,485 direct, 1,358 paraphrase;
127 paraphrases dropped for sharing a 4-word run, 15 chunks answered null). After hard-negative selection: **2,664 training triples**
and 163 validation triples from 1,479 chunks (16 queries dropped for lack of a valid negative). Every chunk used, as positive or
negative, is in the eligible set (assertion passed; hashes in `eligible_manifest.json` and `pairs_manifest.json`).
Observation, not acted on: restricted to the eligible chunks, the base model puts the question's own chunk in its top 8 for 47% of
these machine-written questions (median rank 10), so the training questions are harder or noisier than the hand-written v4 set.

## Addendum E — the single run and its result (2026-11-08; recorded whichever way it fell)
- Training: one spot VM (g2-standard-4, 1x L4, europe-west4-a, auto-delete after 2 h), Python 3.10.12, torch 2.9.1+cu129, sentence-transformers
  6.2.0, transformers 5.20.2 (local embedding used 5.22.2), datasets 5.1.0, accelerate 1.15.0. Input hash matched `pairs_manifest.json`.
  84 steps, 69 s, loss 2.21 -> 0.79, validation loss 0.44. Weights tag `edgar-ft-bge-base@83a78fcb`. The VM and its disk were deleted (verified empty).
  One install problem (an unused audio package) was fixed before training started; no training run was repeated.
- Scoring: control on the main database, candidate on a scratch copy re-embedded with the fine-tuned model (same chunks, corpus fingerprint
  compared), `scripts/finetune-eval.sh`, product defaults, k = 8. Raw per-question results are in `evals/finetune/results/`; the verdict in `decision.json`.
- Verdict from `decide.py`: **ADOPT** (v4 hit@8 +3 = the bar, MRR +0.112; v0..v3 62 -> 66, MRR 0.491 -> 0.545; 4 negative flips <= 5). See ADR 0022 for the caveats.
