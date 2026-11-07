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
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

NLI_MODEL = "cross-encoder/nli-MiniLM2-L6-H768"
ENTAIL_THRESHOLD = 0.5

CITE_RE = re.compile(r"\[(\d{1,2})\]")
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
    missing_companies: list[str] = field(default_factory=list)
    entailment: float | None = None  # best P(entailment) over the cited passages

    @property
    def l1_unsupported(self) -> bool:
        return bool(self.missing_numbers or self.missing_companies)

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
        line = re.sub(r"([.!?])\s*((?:\[\d{1,2}\])+)", r"\2\1", line.strip())  # ". [1]" -> "[1]."
        if not line:
            continue
        for sentence in _sentences(line):
            cites = [int(m.group(1)) for m in CITE_RE.finditer(sentence)]
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


def companies_in(text: str) -> set[str]:
    return {ticker for ticker, rx in _COMPANIES.items() if rx.search(text)}


def check_answer(
    answer: str, evidence: Sequence[dict[str, Any]], nli: NliScorer | None = None
) -> list[ClaimCheck]:
    """`evidence[n-1]` is passage n: a dict with at least `text` and `ticker`."""
    checks: list[ClaimCheck] = []
    for text, cites in split_claims(answer):
        valid = [n for n in cites if 1 <= n <= len(evidence)]
        if not valid:
            checks.append(ClaimCheck(text, cites, uncited=not cites))
            if cites:  # cites only passages that do not exist: verify() already rejects these
                checks[-1].missing_numbers = ["<unknown passage>"]
            continue
        passages = [evidence[n - 1] for n in valid]
        grounded = set().union(*(passage_numbers(p["text"]) for p in passages))
        tickers = {p["ticker"] for p in passages}
        check = ClaimCheck(
            text,
            valid,
            missing_numbers=sorted(numbers_in(text) - grounded),
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
