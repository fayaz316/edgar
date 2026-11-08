# ADR 0021 — Labelled "Inference:" sentences against cite-washing: built, measured, NOT adopted
Status: Accepted (decision: keep prompt v1 as the default; v2 stays available) · Date: 2026-11-08 · Spec and guard: `evals/claims/INFERENCE.md` (frozen before code)

## Context
ADR 0020 made every claim carry a citation; reading the results showed the model then attached citations to comparison and synthesis sentences that no passage states (cite-washing),
so unsupported sentences could look verified.

## Options considered
- **Let the model write comparisons and conclusions as explicit, uncited `Inference:` sentences (no numbers, dates or quotes; at most 40% of the answer), keep citations for facts (prompt v2).** Built and measured.
- **Require a comparison to cite both sides.** The model would just cite two passages and wash it again. Lost.
- **Judge every sentence inside the loop.** Several extra model calls per answer; a gating judge stops being an independent scorer (ADR 0018). Lost.
- **Ban comparisons.** They are the point of those questions. Lost.

## Decision
Do NOT make v2 the default. The pre-registered guard failed on its absolute bar (faithfulness 0.829 against a required 0.90). Prompt v2 and its verify checks remain in the code (`prompt_variant="v2"`; the checks apply to any answer) and the UI shows an "Inference"
badge when a model writes one. Cite-washing therefore remains an open, documented risk (ADR 0020), not a fixed one.

## Evidence (8 new comparative questions; each variant once; the validated judge; guard applied by script)
| | v1 (default) | v2 (inference rule) |
|---|---|---|
| Mean judged faithfulness on cited claims | 0.778 | 0.829 |
| Refusals | 1 | 0 |
| Repairs | 9 | 4 |
| Answers using an `Inference:` label | 0 of 8 | 8 of 8 (1 sentence each, about 1 in 6 to 8) |
| Uncited claims | 0 of 8 | 0 of 8 |
| Prompt-injection attacks that succeeded (frozen 8) | 0 of 8 (ADR 0017) | 0 of 8; benign utility 3 of 3 |
Guard: faithfulness needed B >= A + 0.03 AND B >= 0.90 -> failed the absolute bar; refusals, uncited claims and injection passed.
- **A flaw in my own guard:** v1 refused iq3 (no faithfulness score) while v2 answered it (1.0), so v2's mean includes a question v1's does not. On the 7 questions both answered the means are 0.778 and 0.805, a gain of 0.027, below even the +0.03 bar.
- **Per question the picture is mixed:** v2 faithfulness lower on 4 questions (iq1, iq2, iq4, iq6), higher on 3 (iq5, iq7, iq8), and it answered the one v1 refused.
- **Set-to-set noise is larger than the effect:** v1's own mean was 0.867 on the previous 8 comparative questions (ADR 0020) and 0.778 here.

## Consequences
- **Real, smaller benefits seen:** fewer repairs (9 to 4) and no refusal, i.e. v2 made the model's job easier, plausibly because it no longer has to force citations onto conclusions. That is suggestive, not established (8 questions).
- **Not shown:** that v2 reduces cite-washing. The judge only scores cited claims, so moving weak sentences into the inference bucket raises the number without proving the cited facts got better.
- **The absolute bar (0.90) was my choice.** On this set neither variant could plausibly reach it, which I should have checked when I wrote the guard. It stands because the rule was fixed in advance; lowering it now would make the decision depend on the result.
- **Left open:** a fresh, larger comparison (v2 against v1) judged on matched questions, or surfacing a per-sentence verification state in the UI from an out-of-loop judge.
- **Consumed data:** `inference_questions.yaml` (8 questions) is used once for this decision; the injection set was used a second time as a regression check (DECISION_LOG).
