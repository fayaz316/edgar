"""Parser diagnostics over the raw-HTML cache — fully offline (no SEC, no DB, no quota).

For every cached filing: how many chunks, how they distribute over sections, what share is
unlabeled "Front Matter", the longest chunk, and flags for anything that looks wrong
(e.g. a 10-Q with no MD&A). This is the feedback loop for parser work: change parse.py,
re-run, compare. Heuristics are hints for a human, not verdicts.

Usage: uv run python -m services.ingest.parse_report [TICKER ...]
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass

from services.ingest import raw_cache
from services.ingest.edgar_client import Filing
from services.ingest.parse import parse_filing

REQUIRED = {
    "10-K": {"Business", "Risk Factors", "MD&A", "Financial Statements"},
    # 10-Q Part II Item 1A is often a one-line "no material changes" stub, so not required
    "10-Q": {"Financial Statements", "MD&A"},
}
FRONT_MATTER_WARN = 0.15
EXHIBITS_WARN = 0.20
LONG_CHUNK_WARN = 3000
EMBED_CHUNKS_PER_MIN = 50  # free-tier backfill pace (see embed_backfill.py)


@dataclass(frozen=True)
class FilingReport:
    ticker: str
    form: str
    accession: str
    filed_at: str
    n_chunks: int
    n_chunks_no_tables: int
    chars: int
    sections: dict[str, int]
    front_matter_share: float
    longest_chunk: int
    flags: list[str]


def build_report(filing: Filing, html: str) -> FilingReport:
    chunks = parse_filing(html, filing.form)
    no_tables = parse_filing(html, filing.form, include_tables=False)
    total = sum(len(c.text) for c in chunks) or 1
    by_section = Counter(c.section for c in chunks)
    chars_by_section: Counter[str] = Counter()
    for c in chunks:
        chars_by_section[c.section] += len(c.text)

    front = chars_by_section.get("Front Matter", 0) / total
    exhibits = sum(v for k, v in chars_by_section.items() if k.startswith("Exhibits")) / total
    longest = max((len(c.text) for c in chunks), default=0)

    flags: list[str] = []
    base = "10-Q" if filing.form.upper().startswith("10-Q") else "10-K"
    missing = sorted(REQUIRED[base] - set(by_section))
    if missing:
        flags.append(f"missing sections: {', '.join(missing)}")
    if front > FRONT_MATTER_WARN:
        flags.append(f"Front Matter is {front:.0%} of text (> {FRONT_MATTER_WARN:.0%})")
    if exhibits > EXHIBITS_WARN:
        flags.append(f"Exhibits is {exhibits:.0%} of text")
    if longest > LONG_CHUNK_WARN:
        flags.append(f"longest chunk {longest} chars")
    if not chunks:
        flags.append("NO CHUNKS PRODUCED")

    return FilingReport(
        ticker=filing.ticker,
        form=filing.form,
        accession=filing.accession,
        filed_at=filing.filed_at,
        n_chunks=len(chunks),
        n_chunks_no_tables=len(no_tables),
        chars=total,
        sections=dict(by_section),
        front_matter_share=front,
        longest_chunk=longest,
        flags=flags,
    )


def format_report(reports: list[FilingReport]) -> str:
    lines: list[str] = []
    for r in reports:
        lines.append(
            f"{r.ticker:<5} {r.form:<5} {r.filed_at}  {r.accession}  "
            f"chunks={r.n_chunks} (without tables: {r.n_chunks_no_tables})  "
            f"front={r.front_matter_share:.0%}  longest={r.longest_chunk}"
        )
        ordered = sorted(r.sections.items(), key=lambda kv: -kv[1])
        lines.append("      " + ", ".join(f"{name}:{n}" for name, n in ordered))
        lines.extend(f"      ! {flag}" for flag in r.flags)
    total = sum(r.n_chunks for r in reports)
    flagged = sum(1 for r in reports if r.flags)
    lines.append("")
    lines.append(
        f"{len(reports)} filings, {total} chunks total "
        f"(~{total / EMBED_CHUNKS_PER_MIN:.0f} min to embed from scratch at {EMBED_CHUNKS_PER_MIN}/min; "
        f"less when text is unchanged — re-ingest reuses embeddings)."
    )
    lines.append(f"{flagged} filing(s) with flags.")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    reports = [build_report(f, html) for f, html in raw_cache.iter_cached(argv or None)]
    if not reports:
        print("no cached filings — run `make fetch` first", file=sys.stderr)
        return 1
    print(format_report(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
