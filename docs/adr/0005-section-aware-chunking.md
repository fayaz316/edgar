# ADR 0005 — Section-aware chunking of 10-K / 10-Q filings
Status: Superseded by ADR 0007 (parser v2) · Retroactive · Date: 2026-11-07

## Context
Chunking sets a ceiling on RAG quality: retrieval can only return what the chunks contain.
Filings are long, structured (Items: Business, Risk Factors, MD&A…), and the section a
passage lives in is real signal for both filtering and citation ("Risk Factors, 10-Q filed
2026-08-26" is a better citation than "chunk 4321").

## Options considered
- **Fixed-size windows (e.g. 512 tokens)** — trivial, but cuts across sections and loses
  where a passage came from. Lost.
- **Section-aware, then size-bounded windows** — split on `Item N.` headings, then pack
  paragraphs into ≤1,200-character chunks with 200 characters of overlap. **Won.**
- **Layout/ML parsers** — better on tables, heavier and slower to trust. Deferred.

## Decision
`parse.py`: HTML → text → split at `Item N[A-C].` headings mapped through `KNOWN_SECTIONS`
→ paragraph-boundary windows. Each chunk keeps `(section, seq)`. Headings repeat in the
table of contents, so `seq` runs continuously per section *name*.

## Consequences — and the defects this ADR must not hide
- 🔴 `KNOWN_SECTIONS` is **10-K numbering applied to every form.** In a 10-Q, Item 1 is
  Financial Statements and Item 2 is MD&A; they are labeled "Business" and "Properties".
  Golden anchors inherited those labels.
- 🔴 `html_to_text` **deletes every `<table>`**, so income-statement and segment figures
  are not in the index, and item headings inside tables vanish (the 41% "Front Matter"
  bucket).
- ⚠️ A single very long paragraph is never split; chunks can exceed 1,200 characters.
- **Revision plan (test-first):** (1) record `make eval-retrieval` as the *before* number;
  (2) form-specific section maps and tables kept as text rows, developed offline against the
  cached HTML (`make fetch`); (3) `make reingest` (unchanged text keeps its embedding);
  (4) record the *after* number. A new ADR supersedes this one with the measured result.
