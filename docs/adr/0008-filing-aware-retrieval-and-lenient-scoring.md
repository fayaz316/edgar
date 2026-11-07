# ADR 0008 — Filing-aware retrieval (form type, "latest") and a strict + lenient eval
Status: Accepted — **weakly evidenced** · Date: 2026-11-07

## Context
The diagnosis behind ADR 0007 showed most remaining misses were "right company, right section,
wrong filing": the corpus holds 2-3 filings per company with near-identical text, and a question
rarely says which one it means. Two things followed:
1. Retrieval ignored cues the question does contain ("latest 10-Q", "the quarter", "annual").
2. The eval counted only the one anchored accession, so identical wording from a sibling
   filing scored as a miss.

## Options considered
- **Read cues from the question and scope the search** — `services/gateway/filing_hints.py`:
  `10-Q`/`quarter(ly)` -> 10-Q, `10-K`/`annual` -> 10-K, `latest`/`most recent`/`newest` ->
  each company's newest matching filing. Conflicting cues give no filter. If the scoped search
  returns nothing, repeat unscoped. **Won.**
- **Parse fiscal periods ("Q2 FY2027")** — fiscal calendars differ per company; needs
  per-company data, not a regex. Deferred.
- **Always prefer the newest filing** — would bury legitimately historical questions. Lost.
- **Keep the eval strict only** — hides that some "misses" returned the right text from a
  sibling filing. Lost; but strict stays the headline because it is the harder test.

## Decision
Retrieval applies the hints by default (`infer_filing=True`, with an unscoped fallback). The eval
reports **strict** (exact filing) and **lenient** (same company, any filing) side by side; lenient
never counts another company.

## Evidence — and how weak it is
Same embedder, same index; hints OFF vs ON; each run once. Guard fixed in advance
(`evals/golden/HELDOUT_PROTOCOL.md`, Addendum A): remove hints if combined MRR drops > 0.03
or strict hit@8 drops > 2 questions.

| Set | hit@1 OFF / ON | hit@8 OFF / ON | MRR OFF / ON |
|---|---|---|---|
| golden_v0 (24) | 0.208 / 0.250 | 0.625 / 0.625 | 0.324 / 0.368 |
| held-out v1 (19) | 0.579 / 0.579 | 0.895 / 0.895 | 0.660 / 0.660 |
| combined (43) | | 32 / 32 questions | 0.473 / 0.497 |

The guard passes: no harm. But:
- The rules were written **after** seeing golden_v0 misses, and the whole gain comes from 3
  golden_v0 questions that moved up in rank. That gain is not independent evidence.
- Only **1 of 19** held-out questions contains a cue, so the held-out set barely exercises the
  hints. "No change" there means "not tested", not "confirmed".
- Hit@8 did not change at all; this improves ordering, not recall.
- 24 + 19 questions cannot detect effects under about 2-4 points.

## Consequences
- **Good:** questions that name a form type or ask for the "latest" filing get that filing;
  strict and lenient scores together show how much of a miss is a wrong-filing miss.
- **Bad:** a cue can mislead (e.g. "quarter" inside a 10-K question) — the fallback only helps
  when the scoped search is EMPTY, not when it is merely wrong. "Latest" across companies means
  each company's own latest filing.
- **Revisit trigger:** when the golden set grows with questions from real usage, re-run hints
  OFF vs ON. If there is still no measurable gain, delete the hints rather than keep dead logic.
