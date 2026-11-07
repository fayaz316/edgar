"""Read filing-selection hints out of a question (pure, no IO).

Why: the corpus holds several filings per company (two 10-Ks, two or three 10-Qs). Their text
overlaps heavily, so a question like "latest JPMorgan 10-Q ... provision for credit losses"
is answered equally well, by embedding similarity alone, by last year's 10-K. The question
often says which filing it means; this module reads that and the retriever scopes to it.

Deliberately conservative: an ambiguous or conflicting cue yields NO hint (search everything)
rather than a wrong filter. Fiscal-period parsing ("Q2 FY2027") is left out on purpose —
fiscal calendars differ per company, so it needs per-company data, not a regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_QUARTERLY = re.compile(r"\b10-?q\b|\bquarterly\b|\bquarter\b|\bquarters\b", re.I)
_ANNUAL = re.compile(r"\b10-?k\b|\bannual\b", re.I)
_LATEST = re.compile(r"\b(latest|most recent|newest)\b", re.I)


@dataclass(frozen=True)
class FilingHints:
    form_type: str | None = None  # "10-K" | "10-Q" | None = no preference
    latest: bool = False  # restrict to each company's newest matching filing

    @property
    def active(self) -> bool:
        return self.form_type is not None or self.latest


def parse_filing_hints(question: str) -> FilingHints:
    quarterly = bool(_QUARTERLY.search(question))
    annual = bool(_ANNUAL.search(question))
    form_type = "10-Q" if quarterly and not annual else "10-K" if annual and not quarterly else None
    return FilingHints(form_type=form_type, latest=bool(_LATEST.search(question)))
