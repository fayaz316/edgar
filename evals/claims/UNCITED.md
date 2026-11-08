# Uncited sentences — spec and guard (written BEFORE any code and BEFORE any end-to-end run)

## Problem (measured, ADR 0018)
After the citation-parser fix, 4 sentences in the 30 saved agent answers carry no citation: 3 substantive comparison/summary sentences (two in x-001, one in x-003) and
1 structural line ("The contexts for each company are as follows:"). Nothing verifies an uncited sentence: not the judge, not L1. The system prompt already says every
factual sentence must end with a citation; the model sometimes ignores it, mostly in comparative answers that synthesise across companies.

## The change (only this)
1. An UNCITED sentence is one with no `[n]` (after the parser fix). It is EXEMPT (structural) only if, after markup stripping, it ends with ":" or has at most 3 words.
   Every other uncited sentence is SUBSTANTIVE. (Default is "needs a citation": many real claims name no company, e.g. "These controls hurt demand".)
2. In the agent's verify step, a non-refusal answer containing a substantive uncited sentence is rejected with feedback naming up to 3 such sentences ("cite the passages
   that support it, or remove it"); it uses the existing repair budget and, when that is used up, the answer is refused, exactly like an L1 rejection.
   `INSUFFICIENT_CONTEXT` answers are exempt. A switch (`uncited="off"|"require"`) keeps the old behaviour available.

## Evaluation A — does the detector separate the two classes? (deterministic, run once)
`uncited_labeled.yaml`: 61 SUBSTANTIVE sentences (the 3 real uncited ones; the 46 cited claims from the original saved judge run with their citations removed, so they read like
real model text; 12 synthetic pronoun-only/comparison sentences I wrote) and 13 STRUCTURAL ones (the 1 real one + 12 synthetic transitions and labels). Labels fixed at authoring.
Guard: at least 95% of substantive sentences flagged (at most 3 missed) AND at most 1 of 13 structural sentences flagged.

## Evaluation B — what does it do to real answers? (real agent + the judge, run once per setting)
Fixed question list (`uncited_questions.yaml`): 6 NEW comparative questions plus x-001 and x-003. Each is answered with the rule OFF and ON, once each. Measured: answers containing a
substantive uncited sentence; refusals; repairs; the validated judge's mean per-answer faithfulness on cited claims.
Guard (adopt the rule as default only if ALL hold): answers with a substantive uncited sentence fall to at most 1 of 8 with the rule ON; refusals with the rule ON are at most one more
than OFF; mean judge faithfulness ON is not lower than OFF by more than 0.05; no infrastructure errors in the counted runs (those are re-run, never counted).
If the guard fails the rule stays OFF and is NOT patched and re-run on the same data.

## Honest limits
- Tiny real evidence (4 sentences, 2 answers). Evaluation A's structural class is mostly synthetic, written by me knowing the rule: it checks the rule works as designed, not that it
  matches every real transition the model will ever write.
- Eight questions, one run each, one model: only a large effect would show. Comparative answers are exactly where a forced citation might make text clunky or cause a refusal.
- Requiring a citation does not make the sentence true: a cited sentence is still only as good as L1 and the judge (which share the known blind spots).
- Evaluation B uses the free tier (generator and a flash-lite judge); results are rate-limit sensitive and slow.
