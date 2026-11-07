# ADR 0014 — Claim-level support checking: only the deterministic layer is enforced
Status: Accepted · Date: 2026-11-07

## Context
The agent's verify step (ADR 0013) only checked that each `[n]` points at a retrieved passage. A model can
cite real passages for claims they do not support. A checker, a labeled test set, and the adoption rule
were written BEFORE building or running anything (`evals/claims/PROTOCOL.md`), with safeguards taken from
the specification-gaming literature (Addendum 1).

## Options considered
- **L1: deterministic grounding** (`services/agent/claims.py`): every number in a claim must appear in a
  cited passage, and every company named must be the company of a cited passage.
- **L2: local NLI model** (`cross-encoder/nli-MiniLM2-L6-H768`): the best cited passage must entail the claim.
- **LLM judge (Gemini) inside the loop** — not tried: spends the free quota on every answer, and a judge
  that gates the agent cannot also be the faithfulness scorer without circularity (Insider Knowledge, 2601.13227).
- **Leave verify shallow** — the status quo. Lost.

## Decision
Enforce **L1 only** in the agent (`claim_check="l1"` by default, `"off"` available): an answer with an
ungrounded figure or company goes back to the model with feedback, up to the repair limit, then is refused.
L2 is kept in the code but is not used by the agent. Sentences with no citation are reported, not rejected.
The decision followed mechanically from the protocol's guard.

## Evidence (one run on `claims_v1.yaml`: 18 faithful + 18 unfaithful claims; rules were not changed after it)
| Layer | False-flag on faithful | number | entity | wrong passage | direction | invented cause | overall |
|---|---|---|---|---|---|---|---|
| L1 | 0 of 18 | 4/4 | 4/4 | 1/3 | 0/3 | 0/4 | 9/18 |
| L2 (NLI) | 17 of 18 | 4/4 | 4/4 | 3/3 | 3/3 | 4/4 | 18/18 |
| combined | 17 of 18 | | | | | | 18/18 |

Guard: combined needed false-flag <= 20% (got 94%) -> no. L1 alone needed false-flag <= 10% and number
detection >= 90% (got 0% and 100%) -> yes, so L1 may enforce.

- L2 "detects everything" only because it flags almost every claim, including near-literal restatements
  (entailment 0.01-0.33). I checked that this is not an implementation bug: the entailment index matches the
  model's own label map, and the model scores trivially easy short pairs at 0.99. The setup (a whole
  ~300-token passage as the premise) is the likely cause, and that is not verified. A windowed variant
  would need its own spec and a fresh labeled set; it was not patched in on this set.
- Label audit: a different model (Gemini), blind to kind and to my labels, agreed on 35 of 36 items. The one
  disagreement (f18) is a faithful claim naming "Apple" about a passage that never names the company; my
  labels were left frozen and f18 is a flaw of the set.
- Real run: "commercial paper ... and what is the change?" - the model first stated a computed decrease of
  $6.0 billion; L1 rejected it; the repaired answer restated the grounded figures and dropped the change.

## Consequences
- **Catches:** changed figures and claims borrowed from the wrong company (8 of 8 on the test set).
- **Does not catch:** invented causes or consequences (0 of 4), flipped direction or negation (0 of 3), and
  most true-but-wrongly-cited claims (1 of 3 caught). The in-loop answer can still be unsupported.
- **False-reject risk:** any derived figure (a difference, a sum, a rounded value) is rejected, which can cost
  the user part of what they asked for. Allowing a computed value whose inputs are both in the cited passages
  is a possible variant; it is not specified or tested.
- **Circularity rule:** this checker must not be the Phase 3 faithfulness scorer; that needs a different judge
  (a different model family and/or human-labeled samples).
- **Small and self-authored:** 36 items, claims and perturbation kinds written by me, one labeler plus a blind
  audit. A rate like 100% on 4 items is a lower bound on confidence, not a guarantee.
- **Revisit trigger:** a windowed-NLI or LLM-judge variant specified in writing and tested on a new labeled
  set (claims_v2), or real answers showing L1 rejecting valid computations often.
