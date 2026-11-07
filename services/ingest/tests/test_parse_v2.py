"""Parser v2 behaviour: form-aware sections, Part tracking, tables kept, ToC/XBRL noise gone.

Synthetic fixtures mimic real EDGAR quirks. Real-HTML behaviour is checked separately with
`make parse-report` against the cached filings (see ADR 0005/0006).
"""

from __future__ import annotations

import itertools

from services.ingest.parse import (
    PART_LINE,
    html_to_text,
    parse_filing,
    split_sections,
)

FILLER = (
    "This paragraph carries enough ordinary words about operations, customers, segments, "
    "markets and risks to clear the minimum section length gate used by the parser. "
)

MINI_10Q = f"""
<html><body>
<p>FORM 10-Q cover page text.</p>
<p>PART I. FINANCIAL INFORMATION</p>
<p>Item 1. Financial Statements</p>
<p>{FILLER * 2}Three direct customers represented 16%, 15%, and 13% of total revenue.</p>
<p>Item 2. Management's Discussion and Analysis of Financial Condition</p>
<p>{FILLER * 2}Revenue grew on strong data center demand.</p>
<p>Item 4. Controls and Procedures</p>
<p>{FILLER * 2}Our disclosure controls were effective.</p>
<p>PART II. OTHER INFORMATION</p>
<p>Item 1. Legal Proceedings</p>
<p>{FILLER * 2}Please see Note 12 for legal matters.</p>
<p>Item 1A. Risk Factors</p>
<p>{FILLER * 2}Export controls could restrict sales.</p>
</body></html>
"""


def _names(spans: list[tuple[str, int, int]]) -> list[str]:
    return [s[0] for s in spans]


def test_10q_same_item_number_means_different_sections_per_part() -> None:
    chunks = parse_filing(MINI_10Q, "10-Q")
    sections = {c.section for c in chunks}
    assert {"Financial Statements", "MD&A", "Controls and Procedures"} <= sections
    assert {"Legal Proceedings", "Risk Factors"} <= sections
    # the v1 bug: 10-K numbering applied to a 10-Q
    assert "Business" not in sections
    assert "Properties" not in sections


def test_10q_customer_concentration_is_under_financial_statements() -> None:
    chunks = parse_filing(MINI_10Q, "10-Q")
    hit = next(c for c in chunks if "16%, 15%, and 13%" in c.text)
    assert hit.section == "Financial Statements"


def test_amended_forms_use_the_base_form_map() -> None:
    assert "Financial Statements" in {c.section for c in parse_filing(MINI_10Q, "10-Q/A")}


def test_10k_map_unchanged_for_10k() -> None:
    text = "cover\nItem 1. Business\nwe sell things\nItem 7. Management's Discussion\nrevenue"
    assert _names(split_sections(text, "10-K")) == ["Front Matter", "Business", "MD&A"]


def test_part_line_must_be_short_heading_not_prose() -> None:
    assert PART_LINE.match("PART II. OTHER INFORMATION")
    assert PART_LINE.match("Part I")
    assert PART_LINE.match("PART I — FINANCIAL INFORMATION")
    assert not PART_LINE.match("Part II, Item 1A of our Annual Report on Form 10-K describes risks")
    # prose line that merely starts with 'Part I' must not flip the Part
    text = (
        "PART I. FINANCIAL INFORMATION\nItem 1. Financial Statements\nbody\n"
        "Part II, Item 1A of our Annual Report discusses risk factors in detail and is long enough to be prose\n"
        "Item 2. Management's Discussion\nmore body"
    )
    assert _names(split_sections(text, "10-Q")) == ["Front Matter", "Financial Statements", "MD&A"]


def test_toc_entries_are_not_section_starts() -> None:
    html = f"""
    <p>Forward-looking statements. {FILLER * 3}</p>
    <table>
      <tr><td>Item 1.</td><td>Business</td><td>4</td></tr>
      <tr><td>Item 16.</td><td>Form 10-K Summary</td><td>99</td></tr>
    </table>
    <p>{FILLER * 3}</p>
    <p>Item 1. Business</p><p>{FILLER * 3}</p>
    """
    sections = {c.section for c in parse_filing(html, "10-K")}
    assert "Form 10-K Summary" not in sections  # last ToC row must not swallow the preamble
    assert "Business" in sections


def test_heading_inside_table_cells_is_found() -> None:
    html = f"""
    <table><tr><td>Item 1A.</td><td>Risk Factors</td></tr></table>
    <p>{FILLER * 3}</p>
    """
    assert "Risk Factors" in {c.section for c in parse_filing(html, "10-K")}


def test_heading_split_across_lines_is_found() -> None:
    html = f"<p>Item 1A.</p><p>Risk Factors</p><p>{FILLER * 3}</p>"
    assert "Risk Factors" in {c.section for c in parse_filing(html, "10-K")}


def test_tables_are_kept_as_pipe_rows_with_fragments_merged() -> None:
    html = """
    <table>
      <tr><td>Revenue</td><td>$</td><td>26,044</td><td>$</td><td>13,507</td></tr>
      <tr><td>Net loss</td><td>(</td><td>1,234</td><td>)</td><td>12</td><td>%</td></tr>
    </table>
    """
    text = html_to_text(html)
    assert "Revenue | $26,044 | $13,507" in text
    assert "Net loss | (1,234) | 12%" in text


def test_include_tables_false_drops_them() -> None:
    html = "<p>keep this prose line</p><table><tr><td>Revenue</td><td>26,044</td></tr></table>"
    text = html_to_text(html, include_tables=False)
    assert "keep this prose line" in text
    assert "26,044" not in text


def test_hidden_inline_xbrl_is_removed() -> None:
    html = """
    <div style="display:none"><ix:header><ix:hidden>0001045810 dei:EntityCentralIndexKey</ix:hidden></ix:header></div>
    <p>Visible disclosure text.</p>
    """
    text = html_to_text(html)
    assert "Visible disclosure text." in text
    assert "EntityCentralIndexKey" not in text


def test_overlong_paragraph_is_split_at_sentences() -> None:
    sentence = "The company discloses a relevant fact about its operations here. "
    html = f"<p>Item 1. Business</p><p>{sentence * 60}</p>"
    chunks = parse_filing(html, "10-K")
    assert len(chunks) >= 2
    assert all(len(c.text) <= 1200 + 200 + 80 for c in chunks)  # window + overlap + slack


def test_unique_section_seq_with_repeated_headings_10q() -> None:
    html = (
        MINI_10Q
        + f"<p>PART II. OTHER INFORMATION</p><p>Item 1A. Risk Factors</p><p>{FILLER * 3}</p>"
    )
    keys = [(c.section, c.seq) for c in parse_filing(html, "10-Q")]
    assert len(keys) == len(set(keys))


# --- big Item 15 / MD&A spans that contain the real financial statements -----------------
BODY_LINE = "x" * 99  # one 100-char line (with newline)


def _item15(
    head_lines: int, fs_lines: int, with_exhibits: bool = True, with_fs: bool = True
) -> str:
    parts = ["Item 15. Exhibits, Financial Statement Schedules."]
    parts += [BODY_LINE] * head_lines
    if with_fs:
        parts += ["Report of Independent Registered Public Accounting Firm"]
        parts += [BODY_LINE] * fs_lines
    if with_exhibits:
        parts += ["Exhibit Index", "Exhibit No. | Description | Form"] + [BODY_LINE] * 5
    return "\n".join(parts)


def test_item15_index_then_statements_then_exhibits_is_split_in_three() -> None:
    spans = split_sections(_item15(head_lines=15, fs_lines=300), "10-K")
    assert _names(spans) == [
        "Front Matter",
        "Exhibits and Financial Statement Schedules",
        "Financial Statements",
        "Exhibits and Financial Statement Schedules",
    ]


def test_cross_reference_filer_big_head_becomes_annual_report_body() -> None:
    spans = split_sections(_item15(head_lines=400, fs_lines=300, with_exhibits=False), "10-K")
    assert _names(spans)[1:] == ["Annual Report Body", "Financial Statements"]


def test_item15_without_statement_markers_is_unchanged() -> None:
    spans = split_sections(_item15(head_lines=400, fs_lines=0, with_fs=False), "10-K")
    assert _names(spans)[1:] == ["Exhibits and Financial Statement Schedules"]


def test_small_item15_with_marker_is_left_alone() -> None:
    spans = split_sections(_item15(head_lines=2, fs_lines=3), "10-K")
    assert _names(spans)[1:] == ["Exhibits and Financial Statement Schedules"]


def test_10q_mdna_containing_statements_is_split() -> None:
    body = "\n".join(
        [
            "PART I. FINANCIAL INFORMATION",
            "Item 2. Management's Discussion and Analysis",
            *[BODY_LINE] * 250,
            "Consolidated balance sheets",
            *[BODY_LINE] * 100,
        ]
    )
    assert _names(split_sections(body, "10-Q"))[1:] == ["MD&A", "Financial Statements"]


def test_spans_stay_contiguous_after_refinement() -> None:
    text = _item15(head_lines=400, fs_lines=300)
    spans = split_sections(text, "10-K")
    for (_, _s1, e1), (_, s2, _e2) in itertools.pairwise(spans):
        assert e1 == s2
    assert spans[-1][2] == len(text)
