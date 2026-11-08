# Cite-washing — spec and guard (written BEFORE any code and BEFORE any evaluation run)

## Problem (found by reading results, ADR 0020)
Requiring a citation on every claim made the model attach citations to comparison and synthesis sentences that no passage states ("In contrast, Apple's disclosures place a
stronger emphasis on…", "distinct approaches tailored to their business models"). The judge rejects them, but a reader sees a citation chip and may believe they are verified.
A comparison across passages is an inference; forcing a citation onto it manufactures unearned support.

## The change (only this)
1. **Prompt variant v2** = v1 + the INFERENCE rule (verbatim in `services/agent/graph.py`, INFERENCE_RULE): a sentence that states a fact must end with a citation to a passage that
   states that fact; a comparison or conclusion that no single passage states is an INFERENCE, written as its own sentence starting with the exact label `Inference:`, left uncited,
   containing no numbers, dates or quotations, placed after the cited facts it rests on; never attach a citation to a comparison the cited passage does not itself state.
2. **Verify checks** (apply to every answer when `uncited="require"`): a sentence starting `Inference:` is exempt from needing a citation, BUT the answer is rejected (repair, then refuse, as before) if
   an inference sentence contains a digit or a quotation mark, or if inference sentences are more than 40% of the answer's non-structural sentences (prevents labelling everything as inference).
3. **UI:** the `Inference:` label is shown as a visible badge ("not stated by any single passage").
The default prompt stays v1 until the guard below passes.

## Evaluation (real agent + the validated judge; each variant once per question)
Fixed list `inference_questions.yaml`: 8 NEW comparative questions. Variant A = v1 (current default), variant B = v2, same code otherwise.
Measured: mean per-answer judge faithfulness on CITED claims; refusals; repairs; answers using an `Inference:` label and the share of sentences that are inferences; uncited substantive sentences.
**Guard (adopt v2 as default only if ALL hold):**
 (i)   mean judge faithfulness B >= A + 0.03 AND B >= 0.90;
 (ii)  refusals B <= refusals A + 1;
 (iii) uncited substantive sentences remain 0 of 8 answers in B (the labelled inferences do not count as uncited);
 (iv)  no infrastructure errors in the counted runs (those are re-run, never counted);
 (v)   prompt-injection regression: v2 run once on the frozen attack set (`evals/injection/`): attack success <= 0 of 8 (the measured v1 result) and benign utility 3 of 3.
If any fails, v2 is NOT adopted and is not patched and re-run on the same data.

## Honest limits
- 8 questions, one run each: a faithfulness difference of a few points is within noise. The guard asks for +0.03 and an absolute 0.90, which the noise can fake in either direction.
- An `Inference:` label is an honesty signal, not a verification: the inference sentences themselves are still unchecked. The model could also mislabel a factual claim as an inference to avoid
  citing it; the digit/quote ban and the 40% cap limit this but do not prevent it.
- The judge scores only cited claims. It does not score inference sentences, so a "better" faithfulness number can partly come from moving weak sentences into the inference bucket. That is intended
  (they are no longer pretending to be cited facts) but means the number is not a like-for-like quality measure; the counts of inferences are reported beside it.
- Same-vendor judge (ADR 0018); free-tier pacing; one model.
