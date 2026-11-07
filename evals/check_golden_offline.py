"""Check golden anchors against a FRESH parse of the cached filings — no DB, no quota.

Answers "if I re-ingest with the current parser, which golden items break?" before spending
a minute of embedding quota. For each anchor: is its snippet_hint inside ONE chunk of that
filing, and under the section the anchor names?

  OK            snippet found, under the anchored section
  WRONG_SECTION snippet found, but only under other section(s)  -> re-anchor the section
  NOT_FOUND     snippet not inside any single chunk             -> rewrite the hint (or the
                text moved/changed, e.g. a table row now reads differently)

Usage: uv run python -m evals.check_golden_offline
"""

from __future__ import annotations

import sys
from collections import Counter

from evals.matching import normalize
from evals.schema import EvidenceAnchor
from evals.validate_golden import load_items
from services.ingest import raw_cache
from services.ingest.parse import Chunk, parse_filing


def check_anchor(chunks: list[Chunk], anchor: EvidenceAnchor) -> tuple[str, list[str]]:
    """(status, sections where the snippet was found)."""
    hint = normalize(anchor.snippet_hint)
    found = sorted({c.section for c in chunks if hint in normalize(c.text)})
    if not found:
        return "NOT_FOUND", []
    return ("OK" if anchor.section in found else "WRONG_SECTION"), found


def main() -> int:
    items, errors = load_items()
    if errors:
        print("golden set invalid:", *errors, sep="\n  ")
        return 1
    by_accession = {f.accession: parse_filing(html, f.form) for f, html in raw_cache.iter_cached()}
    tally: Counter[str] = Counter()
    for item in items:
        for anchor in item.expected_evidence:
            found: list[str]
            chunks = by_accession.get(anchor.accession)
            if chunks is None:
                status, found = "NO_CACHED_FILING", []
            else:
                status, found = check_anchor(chunks, anchor)
            tally[status] += 1
            if status != "OK":
                print(
                    f"{status:<14} {item.id:<16} anchored={anchor.section!r} found_in={found} hint={anchor.snippet_hint[:60]!r}"
                )
    print(f"\nanchors: {dict(tally)}")
    return 0 if set(tally) <= {"OK"} else 1


if __name__ == "__main__":
    sys.exit(main())
