# ADR 0020 — Every claim sentence must carry a citation (and the risk that creates)
Status: Accepted (guard passed; one risk found outside the guard, see Consequences) · Date: 2026-11-08 · Spec and guard: `evals/claims/UNCITED.md` (frozen before code)

## Context
After the citation-parser fix (ADR 0018) 4 sentences in 30 saved answers carried no citation: three comparison or summary claims (x-001, x-003) and one heading. Nothing verifies an uncited
sentence: not the judge, not L1. The system prompt already says every factual sentence needs a citation; the model sometimes ignores it, mostly when it synthesises across companies.

## Options considered
- **Reject answers that contain a substantive uncited sentence, with repair feedback (same machinery as L1).** **Won.**
- **Silently drop uncited sentences.** Changes the answer behind the user's back. Lost.
- **Judge every uncited sentence with an LLM inside the loop.** Costs several model calls per answer on a free tier, and a gating judge would stop being an independent scorer (ADR 0018). Lost.
- **Leave it and just report uncited sentences.** The status quo; leaves claims unverifiable. Lost.

## Decision
`services/agent/claims.py`: an uncited sentence is exempt only if it ends with ":" or has at most 3 words; every other uncited sentence needs a citation. In `verify`, a non-refusal answer with such a sentence is
sent back (up to 3 sentences named, "cite the passages that support it, or remove it") using the existing repair budget; when it runs out the answer is refused. Default `uncited="require"`; `"off"` opts out.

## Evidence
- **Evaluation A (labeled sentences, once):** all 61 substantive sentences flagged, 0 of 13 structural sentences flagged (guard: at most 3 missed, at most 1 wrongly flagged). This was expected by construction: the structural class is mostly
  my own synthetic examples, written knowing the rule. It shows the rule does what it says.
- **Evaluation B (real agent + validated judge, 8 comparative questions, each OFF and ON once):**
  | | rule OFF | rule ON |
  |---|---|---|
  | answers with an uncited claim | **5 of 8** | **0 of 8** |
  | refusals | 0 | 0 |
  | repairs (total) | 1 | 6 |
  | mean per-answer judge faithfulness | 0.911 | 0.867 |
  The guard passed (at most 1 of 8 left uncited; at most +1 refusal; faithfulness not down by more than 0.05). The faithfulness margin is narrow: down 0.044 against a 0.05 limit, on 8 answers, so it is better read as "no clear change". The 5 of 8 with the
  rule off, against 2 of 20 on the earlier set, confirms comparison questions are where the gap is.

## Consequences
- **Risk found by reading the results, not covered by the guard: cite-washing.** The newly cited sentences that the judge now rejects are mostly the comparison/synthesis sentences ("In contrast, Apple's disclosures place a stronger emphasis…",
  "distinct approaches tailored to their business models"): judgments across passages that no single passage states. Before the rule these were visibly uncited (an honest signal); now they carry a citation chip the passage does not support, so
  they can LOOK verified when they are not. In the two answers inspected, 4 of 14 judged claims were rejected (also some elaborations beyond the passage). The rule makes every claim visible to the judge and to anyone who clicks the citation; it does
  not make it true. The in-loop L1 check cannot catch this; only the judge (outside the loop) can.
- **Cost:** repairs rose from 1 to 6 across 8 questions (extra model calls and latency on comparison questions).
- **Known gaps:** a claim of 3 words or fewer is treated as structural and escapes; sentences are only checked for HAVING a citation, not for the citation being the right one.
- **Limits:** 8 questions, one run each, one model, a same-vendor judge; Evaluation A's data fits the rule by construction.
- **Next, if this matters:** show per-sentence verification state in the UI (supported / inference / unverified) from an out-of-loop judge, or require comparison sentences to cite passages from both sides and have the judge check them offline.
- **Evaluation data is consumed:** the 74 labeled sentences and the 8 questions are used once for this decision (DECISION_LOG).
