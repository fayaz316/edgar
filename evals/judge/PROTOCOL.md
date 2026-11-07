# Faithfulness judge — protocol (written BEFORE any judge call was made)

## Purpose
Score whether the agent's cited claims are actually supported by the passages they cite, with a scorer that is NOT the
checker that gates the agent. The in-loop L1 check (numbers + companies) is deterministic and shallow; a judge here reads
the claim and its passages and decides. Rule from the literature we read (ADR 0014): a component that gates a system must not also
be the scorer of that system.

## Independence (stated plainly)
- Judge model: `gemini-3.5-flash`. Generator (the agent): `gemini-3.1-flash-lite`. Different model, larger tier.
- NOT fully independent: same vendor and model lineage, so shared blind spots are possible. The judge is also not the deterministic
  in-loop checker. Models available on this key were checked for availability only (2.5-pro and 2.5-flash are listed but retired
  for this account); no model was chosen by looking at results.

## The judge (fixed now; not tuned)
For each claim (a sentence with at least one `[n]` citation, citations removed) the judge receives the claim and the full text of the
cited passages (each with its header: ticker, form, filing date, section) and answers JSON `{"verdict", "reason"}`:
- `supported` only if EVERY factual element of the claim (numbers, dates, companies, direction such as increase/decrease or
  granted/denied, and any cause or consequence) is stated in, or directly entailed by, the cited passages;
- `unsupported` otherwise, including a plausible cause or consequence the passages do not state, a changed figure, the wrong company,
  or a statement that belongs to a different passage.
Passage text is declared untrusted data (the judge must not follow instructions inside it). Temperature 0, one call per claim, no
self-consistency voting. An unparseable reply is retried once; if still unparseable the claim is scored `unsupported` (conservative)
and counted as `invalid` in the report. Verbatim prompt: `evals/judge/judge.py` (JUDGE_PROMPT).

## Step 1 — calibration (is the judge fit to use?)
Run the judge ONCE on `evals/claims/claims_v1.yaml` (36 labeled claims; labels frozen, written before the judge existed).
The judge is declared VALID FOR USE only if ALL hold: false-flag on the 18 faithful claims <= 1; detection of the 18 unfaithful claims >= 15;
invented-cause (`extrapolation`) >= 3 of 4; direction >= 2 of 3; wrong-passage >= 2 of 3; changed-number and wrong-company 8 of 8 combined >= 7.
Otherwise it is reported as NOT VALID and no faithfulness number from it is presented as a measurement. The prompt is not edited after
this run; a failure stays a failure (a new prompt would need its own spec and a fresh calibration set).

## Step 2 — score real agent answers (only if Step 1 is valid)
- **Answerable (20 questions, fixed in questions.py):** the 17 held-out v3 questions plus three multi-step questions (x-001, x-003,
  nvda-10q-009) from golden_v0. The product-default agent (hardened prompt, L1 enforced) answers each with the real corpus.
  Measures: per-answer faithfulness = supported cited claims / cited claims; claim-level supported rate overall; unsupported claims
  listed for reading; uncited sentences counted; answered-rate (not refused) as a utility check.
- **Unanswerable (10 questions, fixed in questions.py):** absent companies, absent periods, absent facts. Correct = the agent refuses.
  Any non-refused answer is judged too (it should be flagged unsupported if it fabricates).
- No pass/fail threshold is set for Step 2: this is the FIRST measurement and becomes the baseline. A future gate needs this baseline
  and a margin written in advance.

## Honest limits (stated now)
- 20 + 10 questions and 36 calibration claims: wide uncertainty; only large effects mean anything.
- The calibration claims and perturbation kinds were written by me; the judge may be good at my kinds and worse at real errors.
- Same-vendor judge: it can share the generator's blind spots and may favour fluent text.
- A judge reading cited passages cannot see evidence the answer omitted or sentences with no citation; uncited sentences are only counted.
- Free-tier rate limits make this slow; latency and cost are reported, not optimised.

## Amendment 1 — judge model changed because of free-tier quota (written BEFORE the re-run; the prompt and guard are unchanged)
What happened: the first calibration attempt used `gemini-3.5-flash`. That model's free tier allows only 20 requests per DAY, and the run was
cut off by the quota after 21 judge calls (the 18 faithful claims and the first three changed-number claims). Every one of those 21 verdicts
matched my labels. That partial result is NOT used for the validity decision: the run did not finish, and the model cannot be used at the
scale needed (36 calibration calls, then roughly 110 for Step 2).
The change: the judge is now `gemini-3.5-flash-lite` (checked for availability only: one trivial call). The prompt, the calibration claims, the
guard and Step 2 are exactly as written above, and the calibration is run from the beginning with the new model.
Independence is WEAKER than first planned: both models are "flash-lite" tier (generator 3.1, judge 3.5), so shared blind spots are more likely and
a smaller judge may be less accurate. The calibration guard exists to catch the second problem; nothing here addresses the first.
The runner is now resumable (each verdict is saved as it arrives) and stops immediately on a daily-quota error instead of retrying.
