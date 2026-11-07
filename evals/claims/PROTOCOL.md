# Claim-level support check — protocol (written BEFORE building the checker or the test set)

## Problem
The agent's verify step checks that each `[n]` points at a retrieved passage. It does not check that
the passage SUPPORTS the sentence. A model can cite real passages for claims they do not support
(wrong number, wrong company, an invented cause). This protocol specifies a checker, a labeled test
set to judge it on, and the rule for whether it may reject answers.

## The checker (fixed now; constants are not tuned)
Input: an answer with `[n]` citations and the numbered evidence passages (each with its ticker).
1. **Claim extraction.** Split the answer into sentences and bullet lines. A claim = a sentence with
   at least one `[n]`; its evidence = the passages it cites. Sentences with no citation are
   REPORTED as "uncited", never rejected (they are often transitions or summaries).
2. **L1 — grounding of specifics (deterministic).**
   a. *Numbers:* every numeral in the claim (after removing `[n]`, form names like 10-K/10-Q, `Q1`-`Q4`,
      `Item 1A`, and bare integers below 10 without `$`, `%` or a decimal point) must appear as a
      token in at least one cited passage, with commas and `$` removed. No unit conversion.
   b. *Companies:* a company named in the claim (NVIDIA, Apple, JPMorgan/JPMorganChase) must be the
      company of at least one cited passage.
3. **L2 — entailment (local NLI model).** Premise = a cited passage (truncated to the model's
   limit), hypothesis = the claim text without citations. Supported iff the best entailment
   probability over the cited passages is >= 0.5. Model: `cross-encoder/nli-MiniLM2-L6-H768`
   (Hugging Face, runs on CPU). Chosen in advance for size; if it fails, the conclusion is about
   THIS model.
4. **Verdict.** Unsupported iff L1 flags it OR L2 does not entail it. Per-layer verdicts are kept for
   the ablation.

## The labeled test set (evals/claims/claims_v1.yaml)
- Passages: a seeded sample of corpus chunks (`md5(c.id::text || 'claims-v1')`, 8 per ticker,
  500-1500 characters). Skips only for boilerplate / table-fragment, each listed with its reason.
- For each kept passage I write one FAITHFUL claim (what a careful answer would say, paraphrased, with
  its citation) and one UNFAITHFUL claim from a fixed list of kinds: `number` (a figure changed),
  `entity` (the wrong company or period), `extrapolation` (a plausible cause or consequence the
  passage does not state), `direction` (increase/decrease or negation flipped), `wrong_passage`
  (true statement, but the cited passage is a different one). Each kind is rotated so every kind
  gets at least 3 items.
- Labels are written at authoring time and never changed after the checker is first run.
- The checker is run ONCE on the whole set; the first run is the report. Failures are NOT patched
  into the rules and re-run on the same set.

## Metrics and guard
Report, per layer and combined, with counts: false-flag rate on faithful claims; detection rate on
unfaithful claims overall and per kind.
**Enforce mode** (reject + repair an answer with an unsupported claim) is allowed only if the combined
checker has false-flag rate <= 20% AND overall detection >= 60% AND `number` detection >= 90%.
Else, if L1 alone has false-flag <= 10% AND `number` detection >= 90%, only L1 may enforce.
Else the checker stays REPORT-ONLY (shown in the trace, never rejects).

## Honest limits (stated now)
- About 40 items: a rate of 70% has a wide interval (roughly +/- 15 points); small differences mean nothing.
- The unfaithful claims are written by me from a fixed list of kinds. Real hallucinations are messier,
  and a perturbation I can define is one a rule can catch more easily than a subtle real one.
- Labels are my judgement; no second labeler. 
- A "real-run audit" (agent answers read by hand) is reported separately and is not part of the guard.

## Addendum 1 — safeguards adopted after reading the specification-gaming literature (written BEFORE the checker's first run on claims_v1)
Sources (read for method, not copied): CapCode 2606.07379 (open-vs-hidden gap as a cheating signal);
"How Reusable Are Benchmarks with Richer Feedback?" 2609.32109 (more criteria and more adaptive uses
make a test set easier to overfit; accept only improvements above a margin); "Insider Knowledge: How
Much Can RAG Systems Gain from Evaluation Secrets?" 2601.13227 (using the judge's own checks inside the
system inflates the judge's score while human assessment lags).

1. **Labeler independence.** I wrote claims_v1 and its labels, and I wrote the checker and the guard.
   Before the checker runs, a DIFFERENT model (Gemini, blind: it sees only passage + claim, not the kind
   or my label) labels all 36 items. Agreement is reported with the disagreements listed. My labels are
   NOT changed afterwards (they are frozen); low agreement is reported as a validity problem of the set.
2. **The in-loop checker may not be the evaluator.** If this checker gates the agent (verify/repair),
   then it cannot be used to score the agent's faithfulness in Phase 3: that needs a different judge
   (a different model family and/or human-labeled samples), or the score is circular.
3. **Seen vs unseen reporting.** Every decision reports the sets that informed the design separately
   from sets that did not (see evals/golden/DECISION_LOG.md). A gain that appears only on seen sets is
   treated as unproven.
4. **Margins, not point differences.** Adoption thresholds in this protocol are margins fixed in advance
   (already so above). With multiple criteria each extra criterion is another chance to pick noise, so no
   criteria are added after the first run.
