from __future__ import annotations

from services.ingest.edgar_client import Filing
from services.ingest.parse_report import build_report, format_report
from services.ingest.tests.test_parse_v2 import FILLER, MINI_10Q


def _filing(form: str) -> Filing:
    return Filing(
        cik="0001045810",
        ticker="NVDA",
        accession="0001045810-26-000075",
        form=form,
        filed_at="2026-08-26",
        period_end=None,
        primary_doc="x.htm",
    )


def test_report_counts_sections_and_has_no_flags_for_a_good_10q() -> None:
    r = build_report(_filing("10-Q"), MINI_10Q)
    assert {"Financial Statements", "MD&A"} <= set(r.sections)
    assert r.flags == []
    assert r.n_chunks >= r.n_chunks_no_tables


def test_report_flags_missing_sections_when_10q_parsed_as_10k_shape() -> None:
    html = f"<p>Item 1. Business</p><p>{FILLER * 3}</p>"
    r = build_report(_filing("10-K"), html)
    assert any("missing sections" in f for f in r.flags)
    assert "Risk Factors" in r.flags[0]


def test_report_flags_front_matter_heavy_filing() -> None:
    html = f"<p>{FILLER * 20}</p><p>Item 1. Business</p><p>{FILLER * 2}</p>"
    r = build_report(_filing("10-K"), html)
    assert r.front_matter_share > 0.5
    assert any("Front Matter" in f for f in r.flags)


def test_format_report_mentions_totals() -> None:
    out = format_report([build_report(_filing("10-Q"), MINI_10Q)])
    assert "1 filings" in out
    assert "NVDA" in out
