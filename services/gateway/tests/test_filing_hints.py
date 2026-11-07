from __future__ import annotations

import pytest

from services.gateway.filing_hints import FilingHints, parse_filing_hints


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What does the latest JPMorgan 10-Q say?", FilingHints("10-Q", True)),
        ("How much stock did NVIDIA repurchase in the second quarter?", FilingHints("10-Q")),
        ("Summarize Apple's annual report risks", FilingHints("10-K")),
        ("What did the 10-K say about competition?", FilingHints("10-K")),
        ("What is the most recent filing about?", FilingHints(None, True)),
        ("What export-control risks does NVIDIA describe?", FilingHints()),
        # conflicting cues -> no form filter rather than a wrong one
        ("Compare the 10-K with the latest 10-Q", FilingHints(None, True)),
        ("How did the quarter compare with the annual figure?", FilingHints()),
    ],
)
def test_parse_filing_hints(question: str, expected: FilingHints) -> None:
    assert parse_filing_hints(question) == expected


def test_active_flag() -> None:
    assert not FilingHints().active
    assert FilingHints("10-Q").active
    assert FilingHints(latest=True).active
