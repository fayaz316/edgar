# ADR 0019 — L1 grounds dates in filing metadata, and stops dates from grounding amounts
Status: Accepted · Date: 2026-11-08 · Amends ADR 0014 · Spec and guard: `evals/claims/L1_DATES.md` (written before the code and before the data was run)

## Context
ADR 0018's first measurement found one answerable question refused by the in-loop L1 check. Reproduced, not assumed: the agent called `list_filings`
(which returns each filing's period end and filing date), then wrote "the period ended July 26, 2026". L1 grounded every number in the cited passage text only,
so it flagged `26`. The repair message ("state figures exactly as they appear in the passages") was wrong for a true metadata date; the model repeated its answer
twice and a correct answer was refused.
A second weakness was found while reading real passages: digits that belong to a DATE in a passage ("April 26, 2026") grounded invented AMOUNTS ("up 26%").

## Options considered
- **Exempt all date-like numbers from L1.** Simple, but a wrong date ("September 26" for "July 26") would pass. Lost.
- **Add filing metadata to the grounding set for every number.** Fixes the case but lets a metadata digit launder an invented amount. Lost.
- **Parse dates; ground a date in the passage OR the metadata the tools returned; keep amounts grounded in passage text only; take date digits out of the amount check
  on both sides.** **Won.**
- **Make the model stop citing metadata dates** (prompt change). The date is true and useful; this would hide, not fix, the checker's gap. Lost.

## Decision
`services/agent/claims.py` now parses dates (`Month D, YYYY`, `D Month YYYY`, ISO, `M/D/YYYY`, `Month YYYY`, `Month D`, month abbreviations) in claims and passages. A claim date is
grounded if its parts match a passage date or a filing date a tool returned in this run (`filed_at` of retrieved passages, `period_end` and `filed_at` from `list_filings`);
full dates match on (year, month, day), month-year on (year, month), month-day on (month, day), bare years on the passage text or metadata. Amounts must still appear in the passage
text, with date digits excluded from the passage's amounts. The agent collects metadata dates from every tool result, and the repair message now says a filing date may come from
that metadata.

## Evidence
- **claims_v2 (20 fresh claims on 4 real passages, labels fixed first), run once, guard applied by script:** the new L1 had 0 of 10 false flags and caught 10 of 10 unfaithful
  claims (4/4 wrong dates, 3/3 laundering, 3/3 changed numbers). The old L1, for comparison: 1 of 10 false flags (the real-failure shape) and 5 of 10 caught; it missed the wrong-month and
  wrong-year dates and every laundering case. The existing claims_v1 contract (CI) still holds. 247 tests pass.
- **Real agent, all 20 answerable questions re-run (the same ones scored in ADR 0018):** exactly one changed: the previously refused question now answers (926,447 shares, the right filing,
  the right section; checked against the corpus); no new refusals; total repairs 2 to 0; no infrastructure errors.

## Consequences
- **The test set fits the design:** I wrote the 20 claims knowing the change, so 10 of 10 shows it does what it was built to do, not that it handles every real date format.
- **Stricter in one way:** a wrong month with a right day or year is now caught (it was not), which can also reject a correct date written in a format the parser does not know
  (for example "Q2 FY2027" or "26 Jul 26"); those fall back to the amount rules and may be false-flagged. Watch for this in real answers.
- **Metadata covers only what the tools returned.** A model that states a date it never saw is flagged, correctly. `period_end` is only returned by `list_filings`, not by search.
- **Not changed:** invented causes, flipped direction, uncited summary sentences, and derived figures (a computed difference is still rejected).
- **Unchanged evaluation set rule:** `claims_v2` is now consumed by this decision (DECISION_LOG); a further checker change needs `claims_v3`.
- **Revisit trigger:** real answers show new false flags on dates, or period end becomes part of every search result.
