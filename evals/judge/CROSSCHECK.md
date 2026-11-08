# Judge cross-check (second model, not human)

**Question.** The faithfulness judge (ADR 0018) is the same vendor as the answering model and was calibrated on claims written
by the project's author. Are its "supported" verdicts trustworthy?

**Method.** 25 of the 49 claims the judge marked *supported* in `answers_run1.jsonl` were sampled with a fixed seed
(`crosscheck_sample.py`). The original run did not save the passages each claim was judged against (the runner now does), so each
claim was checked against the top 3 passages the product retriever returns for the claim text. A second model, from a different
vendor than the judge, read every claim with its passages and gave one of: supported / partial / unsupported
(`crosscheck_verdicts.jsonl`). No human has checked these verdicts.

**Result.** 22 of 25 agree with the judge (88%). The 3 disagreements are *partial*, and all three come from the same comparative
answer (x-003, AI across the three companies): a comparison sentence attributes a framing to a company whose passages do not state it.
That is the cite-washing pattern already documented as an open risk (ADR 0020, ADR 0021). No claim was found to be outright false.

**Limits.** Small sample; weaker than re-reading the judge's own evidence; a model checking a model is not a human check. Read as:
the judge's *supported* verdicts look reliable for single-company factual claims and are too generous on cross-company comparisons.
