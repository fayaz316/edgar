# ADR 0018 — An independent faithfulness judge, calibrated before use, and the first measurement of the agent
Status: Accepted · Date: 2026-11-08 · Protocol: `evals/judge/PROTOCOL.md` (written before any judge call; three amendments, below)

## Context
The agent's in-loop claim check (ADR 0014) is deterministic and shallow: it checks numbers and company names. A component that gates the system
must not also be the scorer of the system (ADR 0014; "Insider Knowledge", 2601.13227). The project needed a scorer that reads a claim and the
passages it cites and decides, and the scorer itself had to be shown fit to use before its numbers meant anything.

## Options considered
- **LLM judge on a different model than the generator, calibrated on labeled claims first.** **Won.**
- **Reuse the in-loop checker as the scorer** — circular; rejected by the rule above.
- **Human labeling of answers** — the gold standard; not available here, and it does not scale to a regression check. Left as the next step.
- **A stronger judge model** — `gemini-2.5-pro` and `2.5-flash` are listed but retired for this account; `gemini-3.5-flash` allows only 20
  requests per DAY on the free tier. Independence therefore had to be weakened (below).

## Decision
- Judge: `gemini-3.5-flash-lite`; generator: `gemini-3.1-flash-lite`. Same tier and vendor, so shared blind spots are possible. The judge is
  not the in-loop checker. Prompt, rubric and calibration guard were frozen before the first run (hash manifest).
- Calibration (Step 1): run once on the 36 labeled claims; valid only if false flags <= 1 of 18, >= 15 of 18 unfaithful caught, and per-kind
  minimums (invented causes 3 of 4, flipped direction 2 of 3, wrong passage 2 of 3, changed number or wrong company 7 of 8).
- Scoring (Step 2): the product-default agent answers 20 answerable questions (the 17 held-out v3 questions plus three multi-step ones) and 10
  unanswerable ones; the judge scores every cited sentence. No pass/fail threshold: this is the baseline.

## Evidence
**Step 1 — the judge is valid for use.** It agreed with my labels on 36 of 36: 0 of 18 faithful claims flagged, 18 of 18 unfaithful caught (4/4
invented causes, 3/3 flipped directions, 3/3 wrong passages, 8/8 numbers and companies), no unparseable replies. The pre-set guard passed.
Honest reading: a perfect score on a small set I wrote myself means the set may be too easy; it shows the judge handles clear-cut errors, not
subtle ones.

**Step 2 — first measurement (corrected; see Amendment 3).**
| | Original run | Corrected |
|---|---|---|
| Answerable questions answered | 19 of 20 | 19 of 20 |
| Cited claims judged | 46 | 54 |
| Claims supported | 42 (91.3%) | 49 (90.7%) |
| Mean per-answer faithfulness | 0.930 | 0.923 |
| Answers containing an unsupported claim | 2 | 3 |
| Sentences with no citation | 12 | 4 |
| Unanswerable questions refused correctly | 10 of 10 | 10 of 10 |
No infrastructure errors in the final data. All 5 unsupported claims were read by hand:
- JPMorgan "retained loans" (3 claims, faithfulness 0.0): retrieval missed the glossary definition (a known miss), and the agent filled in a plausible
  but ungrounded definition. A true positive, and the kind of error the in-loop check cannot see.
- Apple court order (1 claim): the cited risk-factor sentence says "a court order ... preventing it from imposing any commission or fee on certain
  purchases"; the agent added "outside of its apps", true elsewhere in the filing but not in the cited passage. The verdict is defensible; the judge's
  one-line explanation was partly wrong.
- x-003 (1 claim): "NVIDIA ... core focus of their business": a synthesis the passages support only by inference. A strict judge flags it; reasonable people may differ.

## Amendments (all written before the re-run they govern)
1. The first judge model's free tier allowed 20 requests/day; the run was cut off after 21 calls (all matching my labels, not used). Model changed to flash-lite; independence weakened.
2. A transient 503 crashed the first Step-2 attempt on question one; 5xx retries were added to the judge and the agent adapters (no verdict existed yet).
3. Step 2 exposed a defect in shared code: citations written as `[12, 14, 15]` were not parsed, so 8 cited sentences were never judged AND bypassed the
   dangling-citation and L1 checks. Fixed in answer.py, claims.py and the UI, with tests. The original run is kept (`answers_run1_original.jsonl`); only the two
   affected questions were re-run.

## Consequences
- **Sound:** the agent refused all 10 unanswerable questions (no fabrication, including company-present/period-absent cases), and about 91% of its cited claims
  were supported. These are one run on a small set judged by a same-vendor model.
- **Found, not fixed (each needs its own spec and fresh data):**
  - the in-loop L1 check falsely rejected one correct answer (hc-nvda-10q-001: it flagged the day "26" in "period ended July 26, 2026", a date that comes from
    filing metadata, not the passage text) and the agent refused an answerable question;
  - uncited summary or comparison sentences (4 left) are verified by nothing;
  - the worst answer traces to a retrieval miss, so faithfulness and retrieval quality are linked.
- **Limits:** 20 + 10 questions; the judge shares the generator's vendor and tier; calibration claims were written by me; one run each; no human check of the
  judge's "supported" verdicts (only of its "unsupported" ones). Differences smaller than a few claims mean nothing.
- **Free tier shaped the design:** per-day quotas of 20 (some models) make a CI answer-quality gate impractical until a paid or higher-quota judge exists.
- **Next:** a human-labeled sample of "supported" verdicts to check the judge's false-negative rate; a baseline-plus-margin gate on these numbers once the judge is
  trusted; fix the L1 date false-reject and the uncited-sentence gap as separately specified changes.
