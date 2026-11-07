# Eval gate — rules (written BEFORE the gate code or its baseline existed)

## What problem this solves
Every retrieval/agent change so far was judged by hand-run experiments. A gate makes the judgement automatic and
repeatable, so a later change cannot quietly make things worse, and so the frozen evaluation data cannot be edited
to make a change look better.

## Two layers
**Layer 1 — offline, runs in CI on every pull request (no database, no model, no network):**
1. *Frozen-file manifest.* The held-out sets, the claims set and its passages are hashed in
   `evals/baselines/manifest.json`. A test fails if any of them changes. Changing one means running
   `python -m evals.freeze --update` (a deliberate act that shows up in the diff) and adding a DECISION_LOG entry.
2. *Claim-check L1 contract.* The deterministic claim checker is run over `claims_v1.yaml`; it must keep
   false-flag <= 10% on faithful claims and detect >= 90% of changed-number claims (the thresholds that allowed it
   to enforce, ADR 0014).
3. *Gate logic* is unit-tested.

**Layer 2 — full retrieval gate, `make eval-gate` (needs the corpus in Postgres and the local embedder):**
Runs the default retriever over all four question sets and compares per-question results with a committed baseline
(`evals/baselines/retrieval_baseline.json`). It exits non-zero on a regression.

## Regression rules (strict scoring, k = 8; improvements never fail)
FAIL if any of:
- combined strict MRR falls by more than 0.02;
- combined strict hit@8 falls by more than 1 question;
- any single set loses more than 2 hit@8 questions, or more than 0.05 MRR;
- more than 4 "negative flips" in total (a question the baseline answered within the top 8 that now misses; aggregate
  scores can hide these, see RAGFlip 2610.07266).
ERROR (the comparison is not valid, so it is neither pass nor fail): different corpus fingerprint, embedder, k, or
golden-file hashes versus the baseline. The baseline must then be regenerated deliberately.
Margins are small on purpose (they catch breakage, not noise); they are not adoption criteria. Adopting an
improvement still needs the pre-registered protocol (HELDOUT_PROTOCOL.md) and a fresh held-out set.

## Baseline updates
`make eval-gate-baseline` regenerates the baseline. A baseline change in a pull request must be accompanied by an ADR
or DECISION_LOG entry saying why (reviewed by a human; not enforceable by code).

## Honest limits
- The sets are small (78 questions): the margins are tuned to catch obvious breakage, not subtle drift.
- golden_v0 and v1 are retired as *adoption* guards (DECISION_LOG) but are still useful as regression tests.
- Layer 2 is not in GitHub Actions: runners have no corpus or embedding model. Running it there needs a hosted
  corpus snapshot; until then it is a local/pre-push gate. Layer 1 is what CI enforces.
- A gate on retrieval says nothing about answer quality: generation faithfulness still lacks an independent judge.
