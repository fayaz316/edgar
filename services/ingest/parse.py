"""HTML filing -> structure-aware chunks (v2: form-aware, Part-aware, tables kept).

EDGAR HTML is hostile: tables of contents repeat "Item 1A", headings hide in table cells
or split across lines, inline-XBRL ships a hidden fact dump, and 10-K and 10-Q number
their Items differently. This parser stays a transparent heuristic (no ML) and says so:
retrieval quality is measured by the golden set, and `make parse-report` shows what the
parser did to every cached filing.

What changed vs v1 (ADR 0005 -> superseded by the measured result in ADR 0006):
  * 10-K and 10-Q use different section maps; a 10-Q's "Item 1" means Financial
    Statements in Part I but Legal Proceedings in Part II, so we track PART headings.
  * tables are kept as text rows ("Revenue | $26,044 | $13,507") instead of deleted, so
    financial figures and headings that live in table cells reach the index.
  * table-of-contents entries (heading + trailing page number) are not section starts.
  * hidden inline-XBRL (ix:header, display:none) is removed — it is machine noise.
  * over-long paragraphs are split at sentence boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

# --- section maps -----------------------------------------------------------------------
# 10-K: Item numbers are unique across the filing.
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

# 10-Q: Item numbers restart in each Part, so the key is (part, item).
SECTIONS_10Q: dict[tuple[str, str], str] = {
    ("I", "1"): "Financial Statements",
    ("I", "2"): "MD&A",
    ("I", "3"): "Quantitative and Qualitative Disclosures About Market Risk",
    ("I", "4"): "Controls and Procedures",
    ("II", "1"): "Legal Proceedings",
    ("II", "1A"): "Risk Factors",
    ("II", "2"): "Unregistered Sales of Equity Securities",
    ("II", "3"): "Defaults Upon Senior Securities",
    ("II", "4"): "Mine Safety",
    ("II", "5"): "Other Information",
    ("II", "6"): "Exhibits and Financial Statement Schedules",
}

# hyphen, en dash, em dash — headings use all three
_DASHES = "\\-" + chr(0x2013) + chr(0x2014)
# plain concatenation, not f-strings: ruff-format rewrites "{1,3}" inside f-strings
ITEM_LINE = re.compile(
    r"^Item\s+(\d{1,2})\s*([A-C])?\s*(?:[.:" + _DASHES + r"|]|\s|$)",
    re.IGNORECASE,
)
# a real PART heading is a SHORT line; "Part I, Item 1A of our Form 10-K ..." is prose
PART_LINE = re.compile(
    r"^part\s+(i{1,3}|iv)\b[\s.:"
    + _DASHES
    + r"|]*(?:financial information|other information)?[\s|]*$",
    re.IGNORECASE,
)
TOC_ENTRY = re.compile(r"[\s|]\d{1,3}\s*$")  # heading line ending in a page number
MAX_HEADING_LINE = 200

MAX_CHUNK_CHARS = 1200
OVERLAP_CHARS = 200
MIN_SECTION_CHARS = 200  # skip ToC ghosts and fragments
MIN_CHUNK_CHARS = 40

_ROMAN = {"I": "I", "II": "II", "III": "III", "IV": "IV"}
_SUFFIX_CELLS = {")", "%", ")%", "%)"}
_PREFIX_CELLS = {"$", "(", "($", "$("}


@dataclass(frozen=True)
class Chunk:
    section: str
    seq: int
    text: str


# --- HTML -> text -------------------------------------------------------------------------
def _merge_cells(cells: list[str]) -> list[str]:
    """Glue iXBRL cell fragments: '$' + '26,044' + ')' -> '$26,044)'; '12' + '%' -> '12%'."""
    out: list[str] = []
    for cell in cells:
        if not cell:
            continue
        if out and (cell in _SUFFIX_CELLS or out[-1] in _PREFIX_CELLS):
            out[-1] += cell
        else:
            out.append(cell)
    return out


def _clean(s: str) -> str:
    return re.sub(r"[ \t" + chr(0xA0) + r"]+", " ", s).strip()


def _table_to_rows(table: Tag) -> list[str]:
    rows: list[str] = []
    for tr in table.find_all("tr"):
        cells = _merge_cells(
            [_clean(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        )
        if cells:
            rows.append(" | ".join(cells))
    return rows


def html_to_text(html: str, *, include_tables: bool = True) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # inline-XBRL: a hidden machine-readable fact dump that is not human text
    for tag in soup.find_all(["ix:header"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.IGNORECASE)):
        tag.decompose()
    for table in soup.find_all("table"):
        if table.parent is None:  # nested table already removed with its parent
            continue
        rows = _table_to_rows(table) if include_tables else []
        table.replace_with(soup.new_string("\n" + "\n".join(rows) + "\n"))
    text = soup.get_text(separator="\n")
    lines = [_clean(ln) for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# --- sectioning ---------------------------------------------------------------------------
def _is_10q(form: str) -> bool:
    return form.upper().startswith("10-Q")


def _section_for(form: str, part: str | None, key: str) -> str | None:
    if _is_10q(form):
        return SECTIONS_10Q.get((part or "I", key))
    return KNOWN_SECTIONS.get(key)


def split_sections(text: str, form: str = "10-K") -> list[tuple[str, int, int]]:
    """Return [(section_name, start, end)] over the plain text."""
    marks: list[tuple[str, int]] = []  # (section, start_offset)
    part: str | None = None
    offset = 0
    for line in text.split("\n"):
        if _is_10q(form) and len(line) <= 80:
            pm = PART_LINE.match(line)
            if pm:
                part = _ROMAN[pm.group(1).upper()]
        m = ITEM_LINE.match(line)
        if m and len(line) <= MAX_HEADING_LINE and not TOC_ENTRY.search(line):
            key = f"{m.group(1)}{(m.group(2) or '').upper()}"
            section = _section_for(form, part, key)
            if section:
                marks.append((section, offset))
        offset += len(line) + 1
    if not marks:
        return [("Front Matter", 0, len(text))]

    spans: list[tuple[str, int, int]] = [("Front Matter", 0, marks[0][1])]
    for i, (section, start) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(text)
        spans.append((section, start, end))
    return spans


# --- chunking -----------------------------------------------------------------------------
def _split_long(para: str) -> list[str]:
    """Split an over-long paragraph at sentence boundaries (hard-split as a last resort)."""
    if len(para) <= MAX_CHUNK_CHARS:
        return [para]
    pieces: list[str] = []
    buf = ""
    for sentence in re.split(r"(?<=[.!?])\s+", para):
        while len(sentence) > MAX_CHUNK_CHARS:  # no sentence boundary: hard split
            if buf:
                pieces.append(buf)
                buf = ""
            pieces.append(sentence[:MAX_CHUNK_CHARS])
            sentence = sentence[MAX_CHUNK_CHARS:]
        if buf and len(buf) + 1 + len(sentence) > MAX_CHUNK_CHARS:
            pieces.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf:
        pieces.append(buf)
    return pieces


def _chunk_text(text: str) -> list[str]:
    """Paragraph-boundary sliding window, MAX_CHUNK_CHARS with OVERLAP_CHARS."""
    paragraphs = [p for para in text.split("\n") for p in _split_long(para)]
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
    return [c.strip() for c in chunks if len(c.strip()) >= MIN_CHUNK_CHARS]


def parse_filing(html: str, form: str = "10-K", *, include_tables: bool = True) -> list[Chunk]:
    """Filing HTML -> section-labeled chunks with per-section sequence numbers.

    A section can appear multiple times (amendments, repeated headings): seq runs
    continuously per section NAME, so (section, seq) stays unique.
    """
    text = html_to_text(html, include_tables=include_tables)
    chunks: list[Chunk] = []
    seq_by_section: dict[str, int] = {}
    for section, start, end in split_sections(text, form):
        body = text[start:end].strip()
        if len(body) < MIN_SECTION_CHARS:
            continue
        for piece in _chunk_text(body):
            seq = seq_by_section.get(section, 0)
            seq_by_section[section] = seq + 1
            chunks.append(Chunk(section=section, seq=seq, text=piece))
    return chunks
