"""Claim-level support check for cited answers (specified in evals/claims/PROTOCOL.md).

verify (graph.py) only proves a citation points at a retrieved passage. This module asks whether the
passage SUPPORTS the sentence, in two layers:
  L1  deterministic: every number in the claim, and every company it names, must be grounded in the
      cited passages (catches changed figures and borrowed-from-the-wrong-company claims);
  L2  a local NLI model: the best cited passage must entail the claim (catches invented causes,
      flipped direction, and the wrong passage).
Sentences with no citation are reported as `uncited`, never rejected.
All rules and constants are fixed by the protocol; they are not tuned.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

NLI_MODEL = "cross-encoder/nli-MiniLM2-L6-H768"
ENTAIL_THRESHOLD = 0.5

CITE_RE = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")  # "[3]" and "[12, 14, 15]"
_ABBREV = ("U.S.", "Inc.", "Co.", "Corp.", "No.", "vs.", "e.g.", "i.e.", "Ltd.", "N.A.")
_NUMBER_RE = re.compile(r"(\$\s?)?(\d[\d,]*(?:\.\d+)?)(\s?%)?")
_NOISE_RE = re.compile(r"\b10-[KQ]\b|\bQ[1-4]\b|\bItem\s+\d+[A-C]?\b", re.I)
_COMPANIES: dict[str, re.Pattern[str]] = {
    "NVDA": re.compile(r"\bNVIDIA\b", re.I),
    "AAPL": re.compile(r"\bApple\b", re.I),
    "JPM": re.compile(r"\bJPMorgan(?:\s?Chase)?\b", re.I),
}


class NliScorer(Protocol):
    def entail_prob(self, premise: str, hypothesis: str) -> float: ...


@dataclass
class ClaimCheck:
    text: str
    cites: list[int]
    uncited: bool = False
    missing_numbers: list[str] = field(default_factory=list)
    missing_dates: list[str] = field(default_factory=list)
    missing_companies: list[str] = field(default_factory=list)
    entailment: float | None = None  # best P(entailment) over the cited passages

    @property
    def l1_unsupported(self) -> bool:
        return bool(self.missing_numbers or self.missing_dates or self.missing_companies)

    @property
    def l2_unsupported(self) -> bool:
        return self.entailment is not None and self.entailment < ENTAIL_THRESHOLD

    @property
    def unsupported(self) -> bool:
        return not self.uncited and (self.l1_unsupported or self.l2_unsupported)


def strip_markup(text: str) -> str:
    text = CITE_RE.sub("", text).replace("**", "").replace("__", "")
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s+([.,;:!?])", r"\1", text).strip(" \t-*•")


def split_claims(answer: str) -> list[tuple[str, list[int]]]:
    """(sentence text with citations removed, cited passage numbers) for every sentence/bullet."""
    out: list[tuple[str, list[int]]] = []
    for line in answer.splitlines():
        line = re.sub(r"([.!?])\s*((?:\[[\d,\s]+\])+)", r"\2\1", line.strip())  # ". [1]" -> "[1]."
        if not line:
            continue
        for sentence in _sentences(line):
            cites = [
                int(n) for m in CITE_RE.finditer(sentence) for n in re.findall(r"\d+", m.group(1))
            ]
            text = strip_markup(sentence)
            if len(text) >= 8:
                out.append((text, list(dict.fromkeys(cites))))
    return out


def _sentences(line: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for m in re.finditer(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(\[])", line):
        before = line[start : m.start()]
        if before.endswith(_ABBREV):
            continue
        parts.append(before)
        start = m.end()
    parts.append(line[start:])
    return [p for p in parts if p.strip()]


def numbers_in(text: str) -> set[str]:
    """Normalised numerals (no commas, no $/%). Small bare integers are ignored: 'three', '2 of 5'."""
    cleaned = _NOISE_RE.sub(" ", CITE_RE.sub(" ", text))
    found: set[str] = set()
    for m in _NUMBER_RE.finditer(cleaned):
        dollar, digits, percent = m.group(1), m.group(2).replace(",", ""), m.group(3)
        is_small_int = digits.isdigit() and int(digits) < 10
        if is_small_int and not dollar and not percent:
            continue
        found.add(digits)
    return found


def passage_numbers(text: str) -> set[str]:
    """Every numeral in a passage, kept even when small (so a claim's '5.0' can match '5.0')."""
    return {m.group(2).replace(",", "") for m in _NUMBER_RE.finditer(text)}


# ---- dates (spec: evals/claims/L1_DATES.md) -------------------------------------------------------------
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_MONTH_NUM = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
# order matters: longer forms first; matched spans are blanked so later patterns cannot re-match them
_DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)"), "mdy_slash"),
    (re.compile(rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b"), "Mdy"),
    (re.compile(rf"\b(\d{{1,2}})\s+({_MONTH})\.?,?\s+(\d{{4}})\b"), "dMy"),
    (re.compile(rf"\b({_MONTH})\.?,?\s+(\d{{4}})\b"), "My"),
    (re.compile(rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b"), "Md"),
]
_YEAR_RE = re.compile(r"(?<![\d,.])(?:19|20)\d{2}(?![\d,]|\.\d)")
DateKey = tuple[int | None, int | None, int | None]  # (year, month, day); a missing part is None


def _month(name: str) -> int:
    return _MONTH_NUM[name[:3].lower()]


def scan_dates(text: str) -> tuple[list[tuple[str, DateKey]], str]:
    """(dates found as (surface text, key), the text with every date blanked out)."""
    found: list[tuple[str, DateKey]] = []
    for rx, shape in _DATE_PATTERNS:
        for m in rx.finditer(text):
            g = m.groups()
            if shape == "ymd":
                key: DateKey = (int(g[0]), int(g[1]), int(g[2]))
            elif shape == "mdy_slash":
                key = (int(g[2]), int(g[0]), int(g[1]))
            elif shape == "Mdy":
                key = (int(g[2]), _month(g[0]), int(g[1]))
            elif shape == "dMy":
                key = (int(g[2]), _month(g[1]), int(g[0]))
            elif shape == "My":
                key = (int(g[1]), _month(g[0]), None)
            else:
                key = (None, _month(g[0]), int(g[1]))
            found.append((m.group(0), key))
        text = rx.sub(lambda m: " " * len(m.group(0)), text)
    return found, text


@dataclass(frozen=True)
class KnownDates:
    full: frozenset[tuple[int, int, int]] = frozenset()
    ym: frozenset[tuple[int, int]] = frozenset()
    md: frozenset[tuple[int, int]] = frozenset()
    years: frozenset[int] = frozenset()

    def merged(self, other: KnownDates) -> KnownDates:
        return KnownDates(
            self.full | other.full, self.ym | other.ym, self.md | other.md, self.years | other.years
        )

    def covers(self, key: DateKey) -> bool:
        y, m, d = key
        if y is not None and m is not None and d is not None:
            return (y, m, d) in self.full
        if y is not None and m is not None:
            return (y, m) in self.ym
        if m is not None and d is not None:
            return (m, d) in self.md
        return False


def known_dates(keys: Iterable[DateKey], years: Iterable[int] = ()) -> KnownDates:
    full, ym, md = set(), set(), set()
    ys = set(years)
    for y, m, d in keys:
        if y is not None:
            ys.add(y)
        if y is not None and m is not None and d is not None:
            full.add((y, m, d))
        if y is not None and m is not None:
            ym.add((y, m))
        if m is not None and d is not None:
            md.add((m, d))
    return KnownDates(frozenset(full), frozenset(ym), frozenset(md), frozenset(ys))


def parse_metadata_dates(values: Iterable[str]) -> KnownDates:
    """Filing metadata (e.g. '2026-07-26') as known dates; anything unparseable is ignored."""
    keys: list[DateKey] = []
    for v in values:
        found, _ = scan_dates(str(v)[:10])
        keys += [k for _, k in found]
    return known_dates(keys)


def passage_facts(text: str) -> tuple[KnownDates, set[str]]:
    """(dates the passage states, the AMOUNTS it states). Digits that belong to a date or a bare year are not amounts."""
    found, rest = scan_dates(text)
    years = {int(y) for y in _YEAR_RE.findall(text)}
    rest = _YEAR_RE.sub(" ", rest)
    return known_dates((k for _, k in found), years), passage_numbers(rest)


def ground_claim(
    claim: str, passages: Sequence[dict[str, Any]], metadata: KnownDates
) -> tuple[list[str], list[str]]:
    """(claim dates no passage or metadata supports, claim amounts/years no passage supports)."""
    known = metadata
    amounts: set[str] = set()
    for p in passages:
        d, a = passage_facts(p["text"])
        known = known.merged(d)
        amounts |= a
    found, rest = scan_dates(CITE_RE.sub(" ", claim))
    missing_dates = [surface for surface, key in found if not known.covers(key)]
    years = {int(y) for y in _YEAR_RE.findall(rest)}
    missing_years = [str(y) for y in sorted(years) if y not in known.years]
    rest = _YEAR_RE.sub(" ", rest)
    return missing_dates, sorted(set(missing_years) | (numbers_in(rest) - amounts))


# ---- uncited sentences (spec: evals/claims/UNCITED.md) ----------------------------------------------------
def needs_citation(sentence: str) -> bool:
    """A sentence without a citation is exempt only if it is clearly structural: it ends with ':' or has at most 3 words.
    Everything else is a claim and needs a citation (default: needs one; many real claims name no company)."""
    text = strip_markup(sentence)
    return not (text.endswith(":") or len(re.findall(r"[A-Za-z]+", text)) <= 3)


def uncited_substantive(answer: str) -> list[str]:
    """Sentences of an answer that carry no citation and are not structural."""
    return [text for text, cites in split_claims(answer) if not cites and needs_citation(text)]


def companies_in(text: str) -> set[str]:
    return {ticker for ticker, rx in _COMPANIES.items() if rx.search(text)}


def check_answer(
    answer: str,
    evidence: Sequence[dict[str, Any]],
    nli: NliScorer | None = None,
    metadata_dates: Iterable[str] = (),
) -> list[ClaimCheck]:
    """`evidence[n-1]` is passage n: a dict with at least `text` and `ticker`.

    `metadata_dates` are filing dates (ISO strings) the tools returned in this run; they can ground a claim's DATES,
    never its amounts (evals/claims/L1_DATES.md)."""
    metadata = parse_metadata_dates(metadata_dates)
    checks: list[ClaimCheck] = []
    for text, cites in split_claims(answer):
        valid = [n for n in cites if 1 <= n <= len(evidence)]
        if not valid:
            checks.append(ClaimCheck(text, cites, uncited=not cites))
            if cites:  # cites only passages that do not exist: verify() already rejects these
                checks[-1].missing_numbers = ["<unknown passage>"]
            continue
        passages = [evidence[n - 1] for n in valid]
        tickers = {p["ticker"] for p in passages}
        missing_dates, missing_numbers = ground_claim(text, passages, metadata)
        check = ClaimCheck(
            text,
            valid,
            missing_numbers=missing_numbers,
            missing_dates=missing_dates,
            missing_companies=sorted(companies_in(text) - tickers),
        )
        if nli is not None:
            check.entailment = max(nli.entail_prob(p["text"], text) for p in passages)
        checks.append(check)
    return checks


class CrossEncoderNli:
    """Lazy-loads the NLI model (needs the `local-embed` dependency group)."""

    def __init__(self, model_name: str = NLI_MODEL) -> None:
        self.model_name = model_name
        self._model: Any = None
        self._entail_idx = 1

    def entail_prob(self, premise: str, hypothesis: str) -> float:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, max_length=512)
            id2label = {int(k): str(v).lower() for k, v in self._model.config.id2label.items()}
            self._entail_idx = next(i for i, v in id2label.items() if v == "entailment")
        probs = self._model.predict(
            [(premise, hypothesis)], apply_softmax=True, show_progress_bar=False
        )
        return float(probs[0][self._entail_idx])
