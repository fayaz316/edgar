"""HTML filing → structure-aware chunks.

EDGAR HTML is hostile: tables of contents repeat "Item 1A" three times,
headings hide in anchors, spacing is chaos. This parser is deliberately
heuristic — split on "Item N." heading patterns, map to known section
names, fall back gracefully. Imperfect and honest about it; retrieval
quality is measured by the golden set, not assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# Known 10-K/10-Q sections worth keeping; everything else buckets to "Other".
KNOWN_SECTIONS: dict[str, str] = {
    "1": "Business",
    "1A": "Risk Factors",
    "1B": "Unresolved Staff Comments",
    "1C": "Cybersecurity",
    "2": "Properties",
    "3": "Legal Proceedings",
    "4": "Mine Safety",
    "5": "Market for Common Equity",
    "6": "Reserved",
    "7": "MD&A",
    "7A": "Quantitative and Qualitative Disclosures About Market Risk",
    "8": "Financial Statements",
    "9": "Changes in Disagreements with Accountants",
    "9A": "Controls and Procedures",
    "9B": "Other Information",
    "9C": "Disclosure Regarding Foreign Jurisdictions",
    "10": "Directors and Officers",
    "11": "Executive Compensation",
    "12": "Security Ownership",
    "13": "Certain Relationships",
    "14": "Principal Accountant Fees",
    "15": "Exhibits and Financial Statement Schedules",
    "16": "Form 10-K Summary",
}

MAX_CHUNK_CHARS = 1200
OVERLAP_CHARS = 200
MIN_SECTION_CHARS = 200  # skip ToC ghosts and fragments


@dataclass(frozen=True)
class Chunk:
    section: str
    seq: int
    text: str


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "table"]):
        # tables out: exhibit indexes and ToC tables carry noise.
        # Financial-statement tables land in the "Financial Statements" prose.
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def split_sections(text: str) -> list[tuple[str, int, int]]:
    """Return [(section_name, start, end)] over the plain text."""
    marks: list[tuple[str, int]] = []  # (section, start_offset)
    for match in re.finditer(r"(?m)^Item\s+(\d{1,2})([A-C])?\.?\s", text):
        item_no = match.group(1)
        letter = (match.group(2) or "").upper()
        key = f"{item_no}{letter}"
        section = KNOWN_SECTIONS.get(key)
        if section:
            marks.append((section, match.start()))
    if not marks:
        return [("Front Matter", 0, len(text))]

    spans: list[tuple[str, int, int]] = [("Front Matter", 0, marks[0][1])]
    for i, (section, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        spans.append((section, start, end))
    return spans


def _chunk_text(text: str) -> list[str]:
    """Paragraph-boundary sliding window, MAX_CHUNK_CHARS with OVERLAP_CHARS."""
    paragraphs = text.split("\n")
    chunks: list[str] = []
    buffer: list[str] = []
    size = 0
    for para in paragraphs:
        if size + len(para) + 1 > MAX_CHUNK_CHARS and buffer:
            chunks.append("\n".join(buffer))
            # keep tail for overlap
            tail = "\n".join(buffer)
            buffer = [tail[-OVERLAP_CHARS:]] if len(tail) > OVERLAP_CHARS else []
            size = len(buffer[0]) if buffer else 0
        buffer.append(para)
        size += len(para) + 1
    if buffer:
        chunks.append("\n".join(buffer))
    return [c.strip() for c in chunks if len(c.strip()) >= 40]


def parse_filing(html: str) -> list[Chunk]:
    """Filing HTML → section-labeled chunks with per-section sequence numbers.

    A section can appear multiple times (ToC + real heading, amendments):
    seq runs continuously per section NAME, so (section, seq) stays unique.
    """
    text = html_to_text(html)
    chunks: list[Chunk] = []
    seq_by_section: dict[str, int] = {}
    for section, start, end in split_sections(text):
        body = text[start:end].strip()
        if len(body) < MIN_SECTION_CHARS:
            continue
        for piece in _chunk_text(body):
            seq = seq_by_section.get(section, 0)
            seq_by_section[section] = seq + 1
            chunks.append(Chunk(section=section, seq=seq, text=piece))
    return chunks
