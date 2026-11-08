# L1 date handling — spec and guard (written BEFORE any code change and BEFORE claims_v2 was run)

## Problem (reproduced, not assumed)
Asking "In NVIDIA's most recent quarterly report, how many shares went to key employees in its May 2026 acquisition?" the agent called
`list_filings` (which returns each filing's `period_end` and `filed_at`), then wrote "the period ended July 26, 2026". The L1 check
(ADR 0014) grounds every number in the CITED PASSAGE TEXT, so it flagged `26`; the repair feedback ("state figures exactly as they appear
in the passages") was wrong for a true metadata date, the model repeated itself, and a correct answer was refused (ADR 0018).
A second, opposite weakness was noticed while reading real passages: digits that belong to DATES inside a passage ("April 26, 2026")
currently ground invented AMOUNTS ("up 26%"), because the passage's date digits are in the grounding set.

## The change (only this)
1. Parse dates in claims and passages: `Month D, YYYY`, `Month D YYYY`, `D Month YYYY`, `YYYY-MM-DD`, `M/D/YYYY`, `Month YYYY`, `Month D` (month names and
   3-letter abbreviations, optional period).
2. A claim date is GROUNDED if its parts match a date in the cited passage text OR a date from filing metadata the tools returned in this run
   (`filed_at`, `period_end`): full date -> (year, month, day) must match; month+year -> (year, month); month+day -> (month, day); a bare
   year -> the year appears in the passage text or in metadata. An ungrounded claim date is reported as `missing_dates` and counts as unsupported.
3. Digits that belong to a parsed date are removed from the AMOUNT check, on both sides: a date's digits can no longer ground an amount in the
   passage, and a grounded date's digits are not re-checked as amounts in the claim. Amounts (anything outside a date expression) must still
   appear in the cited passage text; metadata can never ground an amount.
4. The agent collects metadata dates from every tool result it receives (`list_filings` rows: `period_end`, `filed_at`; retrieved passages: `filed_at`).
   With no metadata passed (the default), only rules 1-3's stricter date matching applies.

## Fresh labeled data (claims_v2.yaml, authored before the change)
20 claims over 4 real 10-Q passages with their real filing dates. 10 faithful (6 "metadata date" claims that cite a filing date, 4 plain) and 10 unfaithful:
4 wrong dates (including a right-day-wrong-month case and a day that exists in the passage under a different year), 3 "laundering" claims (an invented amount
whose digits equal a date digit in the passage), 3 changed numbers. Labels were fixed at authoring time.

## Guard (the new L1 on claims_v2, run ONCE; the old L1 is reported for comparison only)
Adopt the change only if ALL hold: false flags on the 10 faithful claims <= 1, and the real-failure shape (a claim whose date exists only in metadata) is not flagged;
wrong dates caught >= 3 of 4; laundering caught 3 of 3; changed numbers caught 3 of 3; AND the existing claims_v1 contract still holds in CI (false flags <= 10%
on faithful claims, changed numbers caught >= 90%). If it fails, it is NOT adopted; the checker is not patched and re-run on the same set.

## Honest limits
- 20 claims written by me, the same person who designed the change: the cases fit the design. The guard protects against breaking the old behaviour, not
  against unforeseen real-world formats.
- Date formats outside the list above are not parsed (their digits fall back to the amount rules, which may produce false flags).
- Metadata dates only cover what the tools returned in the run; a model that states a date it never saw will be flagged, correctly.
- It does not touch the other known gaps (uncited sentences, invented causes).
