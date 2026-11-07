"""Parser unit tests — run in CI with no network, no DB, no fixtures on disk."""

from __future__ import annotations

from services.ingest.parse import Chunk, _chunk_text, parse_filing, split_sections

MINI_10K = """
<html><body>
<p>ACME CORPORATION</p>
<p>This is the cover page and table of contents. Item 1A appears here as noise too.</p>
<p>Item 1. Business</p>
<p>ACME builds widgets. We operate in one segment. Our customers include industrial firms.
We sell through distributors and direct channels across 40 countries and 3 regions.
Our strategy is to make better widgets every year with disciplined investment.</p>
<p>Item 1A. Risk Factors</p>
<p>Our business could be harmed if widget demand declines. Concentration of revenue
in three customers is material. Supply chain disruptions could increase costs.
A pandemic, war, or tariff regime could reduce demand for widgets globally.
We may fail to attract and retain engineering talent in competitive markets.</p>
<p>Item 7. Management's Discussion and Analysis</p>
<p>Revenue grew 12% driven by volume. Margins expanded 40 basis points.
Data center demand accelerated. We expect capital expenditures of $500 million.
Inflation impacted component costs modestly during the reported period.</p>
<p>Item 8. Financial Statements and Supplementary Data</p>
<p>The consolidated statements are included in this report as noted elsewhere herein.</p>
</body></html>
"""


def test_split_sections_finds_known_items() -> None:
    text = "Cover stuff\nItem 1. Business\nWe do things.\nItem 1A. Risk Factors\nRisks exist."
    spans = split_sections(text)
    names = [s[0] for s in spans]
    assert "Business" in names and "Risk Factors" in names
    assert spans[0][0] == "Front Matter"


def test_parse_filing_labels_and_sequences() -> None:
    chunks = parse_filing(MINI_10K)
    sections = {c.section for c in chunks}
    assert "Business" in sections
    assert "Risk Factors" in sections
    assert "MD&A" in sections
    # every chunk's seq is unique within its section
    keys = [(c.section, c.seq) for c in chunks]
    assert len(keys) == len(set(keys))
    # citations require non-empty text
    assert all(len(c.text) >= 40 for c in chunks)


def test_chunk_text_respects_max() -> None:
    paragraphs = [f"Paragraph {i} with some words to give it length and body." for i in range(60)]
    for piece in _chunk_text("\n".join(paragraphs)):
        assert len(piece) <= 1200 + 60  # window + one paragraph slack


def test_chunk_is_frozen_dataclass() -> None:
    c = Chunk(section="x", seq=0, text="y" * 50)
    assert c.section == "x"


def test_duplicate_section_headings_stay_unique() -> None:
    """Real filings repeat 'Item 1.' in ToC and body — (section, seq) must not collide."""
    dup = (
        MINI_10K
        + """
    <p>Item 1. Business (again, as filings love to do)</p>
    <p>Second Business passage with enough length to clear the fragment filter.
    More words about widgets, operations, strategy, customers, and competition
    so this section survives the minimum-length gate and produces chunks.</p>
    """
    )
    chunks = parse_filing(dup)
    keys = [(c.section, c.seq) for c in chunks]
    assert len(keys) == len(set(keys)), "duplicate (section, seq) keys"
    assert sum(1 for k in keys if k[0] == "Business") >= 2  # both occurrences kept
