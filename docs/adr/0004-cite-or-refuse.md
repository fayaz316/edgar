# ADR 0004 — Cite-or-refuse: unverifiable answers are suppressed
Status: Accepted (retroactive) · Date: 2026-11-07

## Context
The product answers questions about SEC filings for people who act on the numbers. A
fluent answer with an invented figure or a fake source is worse than no answer: it is
believed. The model can be instructed to cite, but instructions are not guarantees.

## Options considered
- **Trust the model's output** — no. Prompts fail silently.
- **Show the answer with a warning when citations look wrong** — users skim warnings. Lost.
- **Strip the bad citations and keep the prose** — leaves uncited claims looking supported. Lost.
- **Validate after generation; on failure replace the answer with an explicit refusal** — **Won.**

## Decision
The model must answer only from numbered passages and end every factual sentence with
`[n]`; if the passages lack the answer it must say `INSUFFICIENT_CONTEXT`. After generation
we enforce, in code (`answer.py`, pure functions): (1) any citation outside the retrieved
set → refuse; (2) no valid citation at all → refuse; (3) otherwise return the answer with
each citation resolved to its source (filing, section, excerpt). Returning nothing is an
acceptable outcome; returning something unverifiable is not.

## Consequences
- ✅ A user can never be shown a citation that doesn't exist in the evidence we retrieved.
- ⚠️ **A citation that exists is not a claim that is supported.** We check the reference,
  not the truth of the sentence. Faithfulness (LLM-judge + golden answers) is Phase 3.
  Don't describe this as "verified answers" in a demo — describe it as "citation-checked".
- ⚠️ We require ≥1 citation, not one per sentence, even though the prompt asks for that.
- ⚠️ The `[n]` pattern could also match footnote-style `[1]` text quoted from a filing.
- ⚠️ Over-refusal costs usefulness. The Phase 3 *refusal-correctness* metric measures both
  directions (refuse when you should, answer when you can).
- **Revisit trigger:** false-refusal rate on answerable golden questions, or any case where a
  cited passage does not support the sentence it is attached to.
