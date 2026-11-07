# ADR 0007 — Parser v2: form-aware sections and tables kept as text
Status: Accepted · Supersedes ADR 0005 · Date: 2026-11-07

## Context
ADR 0005 recorded three known defects in the original parser and committed to a
test-first revision: measure *before*, change the parser, measure *after*.

- 10-K item numbering was applied to every form, so 10-Q Item 1 (Financial Statements) and
  Item 2 (MD&A) were labeled "Business" and "Properties".
- Every `<table>` was deleted, so income-statement and segment figures were not indexed.
- Golden anchors had inherited the wrong labels (repaired separately in `8dfe840`).

Parser v2 (`4d56029`, `833a3d6`) adds form-aware section maps, Part tracking, tables kept
as text rows, and labeling of financial statements that live inside Item 15 / MD&A.

## How it was measured
One variable at a time. Same 11 cached filings, same golden set (24 answerable questions,
k=8), same embedder (`BAAI/bge-base-en-v1.5`, ADR 0006). Only the parser changed.
Results: `evals/results/baseline-old-parser.json` and `after-parser-v2.json`.

| Metric | Old parser | Parser v2 |
|---|---|---|
| hit@1 | 0.167 | 0.208 |
| hit@3 | 0.417 | 0.417 |
| hit@5 | 0.500 | 0.542 |
| hit@8 | 0.667 (16/24) | 0.625 (15/24) |
| MRR | 0.315 | 0.324 |
| Hit, but section label differs from anchor | 7 questions | 2 questions |
| Misses | 8 | 9 |
| Numeric questions, MRR | 0.354 | 0.417 |
| Comparative questions, hit@8 (n=3) | 0.333 | 0.000 |

## Options considered
- **Keep the old parser and patch labels only** — would fix citations but leave tables
  out of the index. Lost: tables are where financial figures live.
- **Parser v2 (chosen)** — fixes labels, keeps tables, tested offline against cached HTML.
- **Layout/ML parser** — still deferred (ADR 0005). Nothing here shows the HTML-to-text
  route has hit its ceiling.

## Decision
We will keep parser v2 as the ingest parser.

The reason is **correctness of citations, not retrieval recall**. Wrong-label cases fell
from 7 to 2, and citations show the section label to the reader (ADR 0005, ADR 0004). The numbers do
**not** show a recall improvement, and this ADR does not claim one.

## Consequences
- **Good:** 10-Q sections are labeled correctly; tables are in the index; numeric MRR rose.
- **Neutral / honest:** hit@8 moved from 16/24 to 15/24. One question is worth about 4
  points on 24 questions, so this is within noise and neither a gain nor a regression
  can be claimed. The comparative drop (n=3) is likewise too small to interpret.
- **Key finding:** 8 of the 9 misses are the same questions as before
  (`nvda-10q-002/004/005`, `nvda-10k-007`, `aapl-10k-008`, `jpm-10q-005`, `x-001`,
  `x-003`). Parsing is therefore not the main bottleneck; the cause lies elsewhere
  (embedder, query/chunk matching, or the anchors themselves) and is **not yet diagnosed**.
- **Newly missed:** `nvda-10q-009` (was rank 2). Worth inspecting; do not assume it is noise.
- **Weak eval:** 24 questions cannot detect differences smaller than about 4 points.
  Growing the golden set is a prerequisite for any further claim about retrieval changes.
- **Revisit trigger:** after the reranker is built and the persistent misses are
  diagnosed, re-run the same comparison. If hit@8 stays below the Phase-1 exit criterion,
  open a new ADR on the chosen fix.
