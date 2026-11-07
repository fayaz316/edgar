# Held-out set — protocol (written BEFORE sampling or measuring; do not edit afterwards)

Why: golden_v0 (24 answerable questions) was used to diagnose retrieval and to choose fixes.
Anything tuned against it can look better than it is. A held-out set is a second, frozen
exam that no change was designed against. With so few questions it can still only catch
big effects; it is a guard against self-deception, not proof.

## Building it (golden_v1_heldout.yaml)
1. Sample chunks with a fixed seed: `ORDER BY md5(c.id::text || 'heldout-v1')`, per ticker and
   form type, over chunks with 500-1500 characters. The seed is fixed here so the sample
   cannot be re-rolled after seeing results.
2. Walk each ticker/form list in that order. Skip a chunk only for a stated reason:
   `boilerplate` (cover page, signatures, exhibit lists), `table-fragment` (numbers with no
   readable sentence), `no-standalone-question` (cannot be asked without the chunk).
   Every skip is recorded in the YAML header, with the reason.
3. Write the question from the chunk the way a user would ask it, WITHOUT running any search.
   Name a filing or period only if a user plausibly would. Do not adjust wording to suit any
   retriever variant.
4. The anchor `snippet_hint` is a contiguous phrase copied from the chunk (>= 8 characters,
   usually 4-10 words) that carries the answer. Chosen at authoring time; never changed
   after any retrieval result is seen.
5. Freeze: after the first retrieval run, no question or anchor in this file is edited.
   A flawed item stays in and is reported as flawed.

## Measuring
- Every retriever variant runs ONCE per set. Nothing is re-run after a tweak.
- Reported per set and combined: strict hit@1/@8 and MRR (primary), lenient alongside.
- Variants compared: (0) current main retriever = control; (1) control + OR-keyword leg.

## Pre-registered decision rule for the keyword-leg change
The change is adopted on MECHANISM, not on the score: the current keyword leg requires every
query word in one chunk, so it returns nothing for natural-language questions (to be counted
over golden_v0 and the held-out set). Scores act only as a guard. Reject the change if, on
the combined set, strict hit@8 falls by more than 2 questions or MRR falls by more than
0.03 versus the control. A gain is reported but is not a reason to adopt on its own.

## Addendum A (written after the keyword-leg run, before the filing-hint run)
The keyword-leg result was recorded first: control vs OR-keyword, combined 43 questions,
strict MRR 0.497 -> 0.437 (limit was -0.03) => REJECTED under the rule above; default stays AND.
The held-out set was therefore already used once for a decision. No further variant will be
tuned on it.

One more check is owed, because the earlier filing-hint change (form type / "latest" read from
the question) was designed after seeing golden_v0 misses and was never tested on unseen data:
run the control retriever with hints ON vs OFF, once, on both sets. Same guard, symmetric:
if hints ON is worse than OFF on the combined set by more than 0.03 MRR or more than 2 strict
hit@8 questions, remove the hints from the default path. A gain is reported but is not a reason
to keep them beyond the mechanism already stated in filing_hints.py.

## Addendum B — second held-out sample (written BEFORE sampling; golden_v2_heldout.yaml)
Purpose: v1 has been used for two decisions (keyword leg, filing hints) and cannot judge
another. v2 exists so the NEXT retrieval change (e.g. IDF-aware keyword scoring, weighted RRF)
is judged on questions no change was designed against.

Same rules as above, with these differences, all fixed now:
1. **Seed:** `md5(c.id::text || 'heldout-v2')`. The 24 chunks sampled for v1 (used or skipped)
   are excluded so the two sets cannot share a source chunk.
2. **Anti-echo rule:** v1 questions reused the source wording, which made them easier than real
   use (control hit@8 0.895 vs 0.625 on golden_v0). In v2 the question must not contain any
   run of 4 consecutive words from the anchor snippet; it is checked mechanically after
   authoring, and a failing question is reworded BEFORE any search is run.
3. **Cues:** a user's real question sometimes names a form or "latest filing". Where a
   question plausibly would, include the cue; do not add cues to favour or test any variant.
4. **Use:** the control retriever is run once to record a baseline. No variant is run on v2
   until it has been specified in writing (what it changes, what the guard is). Each variant is
   run once. Nothing on v2 is edited after the control run.

## Addendum C — v2 control run (recorded once; v2 is now FROZEN)
Control = current default retriever (AND keyword leg, filing hints ON, local bge, k=8), 18 questions.
Strict: hit@1 0.167, hit@3 0.500, hit@8 0.556 (10/18), MRR 0.303. Lenient hit@8 0.611, MRR 0.349.
Misses: hb-aapl-10q-001, hb-jpm-10k-001, hb-jpm-10q-001/002/003, hb-nvda-10k-002, hb-nvda-10q-002/003.
For comparison, same retriever: golden_v0 hit@8 0.625 / MRR 0.368; v1 hit@8 0.895 / MRR 0.660.
Reading: the anti-echo rule worked; v1 had 4 of 19 questions sharing a 4-word run with their
anchor and scores far higher. v2 is the better guard. No miss on v2 has been diagnosed, on purpose:
reading why they fail is the first step toward tuning to them. Any variant must be specified in
writing first (what it changes, what the guard is), then run once.

## Addendum D — Variant K: BM25 keyword leg. SPECIFICATION AND GUARD (written before any code or run)

**Why this change.** Verified defect (ADR 0009): the AND keyword leg is empty for natural-language
questions. The OR fix failed because plain `ts_rank_cd` has no inverse-document-frequency (IDF)
weighting, so common words ("preferred stock", "December 31, 2025", company names) score like
rare, informative ones. BM25 is the standard answer to exactly that: it down-weights common terms.
Chosen for that mechanism, not because of any question on v2 (no v2 miss has been read).

**What changes (only this).** The keyword leg, when `keyword="bm25"`:
1. Query lexemes = distinct lexemes of `to_tsvector('english', question)` (Postgres stopword
   removal and stemming, same config as the chunks).
2. Candidates = chunks (within the usual filters) containing at least one lexeme.
3. Score = sum over query lexemes of `idf * tf*(k1+1) / (tf + k1*(1 - b + b*dl/avgdl))`, with
   `idf = ln(1 + (N - df + 0.5)/(df + 0.5))`, **k1 = 1.2, b = 0.75** (textbook defaults),
   `tf` = occurrences in the chunk, `dl` = chunk length in lexemes, `df` counted per query,
   `N`/`avgdl` over all chunks.
4. Top 30 by score go into the SAME RRF fusion (equal weight, k=60, pool 30) as today.
Everything else — embedder, semantic leg, filing hints, k=8, scoring — is untouched.

**Fixed now, not to be tuned:** k1, b, the idf formula, pool size 30, RRF weights. If the result
is disappointing these do NOT get adjusted and re-run on these sets.

**Measurement.** Control = current default (AND keyword leg), hints ON, local bge. Variant K =
same with `--lexical bm25`. Each run ONCE on golden_v0 (24), held-out v1 (19), held-out v2 (18).
Control numbers already recorded in evals/results/ (control-golden_v0, control-heldout_v1,
control-heldout_v2). Strict metrics are primary.

**Guard (all must hold to adopt K as default):**
 (i)   combined (61 questions) strict MRR improves by at least +0.03 over control;
 (ii)  no single set loses more than 2 strict hit@8 questions, or more than 0.05 MRR;
 (iii) combined strict hit@8 count is not lower than control.
Otherwise K is NOT adopted: it stays an opt-in flag, off by default. A result between -0.03 and
+0.03 MRR is "inconclusive", which also means not adopted (extra code needs evidence of benefit).
Either outcome is recorded in ADR 0010.

**Reported but not decisive:** per-question wins/losses; lenient scores; how many questions get at
least one keyword candidate; wins vs losses by set.

**Honest limits.** 61 questions: one question is about 1.6 points of hit@8, and an MRR gap of 0.03
is within noise. The guard prevents adopting an obvious regression or an unproven change; it does
not prove an improvement. After this run v2 has been used for a decision; the next idea needs a
new unseen set (v3, new seed, same rules) written first.

## Addendum E — Variant K result (each run once; guard applied by script, not by judgment)
| Set | hit@8 control -> K | MRR control -> K | questions better / worse |
|---|---|---|---|
| golden_v0 (24) | 15 -> 17 | 0.368 -> 0.447 | 9 / 4 |
| held-out v1 (19) | 17 -> 17 | 0.660 -> 0.634 | 6 / 4 |
| held-out v2 (18) | 10 -> 16 | 0.303 -> 0.446 | 9 / 2 |
| combined (61) | 42 -> 50 | 0.440 -> 0.505 (+0.065) | 24 / 10 |
Guard: (i) +0.065 >= +0.03 PASS; (ii) worst single-set change is v1 at -0.026 MRR, 0 hit@8: PASS;
(iii) 50 >= 42 PASS. => ADOPTED as the default keyword leg (ADR 0010).
Descriptive only: among the 34 questions whose rank changed, 24 improved (sign test, two-sided
p about 0.02). v1, the set with echoed wording, is the one set that did not improve.
Consumed: golden_v0, v1 and v2 have now all informed decisions. The next retrieval change needs a
new unseen set (v3, new seed, same rules) written BEFORE the change is run.
