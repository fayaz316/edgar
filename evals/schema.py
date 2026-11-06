"""Golden-set schema — the contract the CI gate will enforce (Phase 3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class EvidenceAnchor(BaseModel):
    accession: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    section: str = Field(min_length=1)
    snippet_hint: str = Field(min_length=8)  # must be findable in corpus


class GoldenItem(BaseModel):
    id: str = Field(pattern=r"^[a-z]+(-[a-z0-9]+)*-[0-9]{3}$")
    question: str = Field(min_length=8, max_length=300)
    answer_type: Literal["grounded", "numeric", "refusal", "comparative"]
    expected_evidence: list[EvidenceAnchor] = Field(default_factory=list)
    must_not_appear: list[str] = Field(default_factory=list)
    tags: list[str] = Field(min_length=1)
    difficulty: Literal["easy", "medium", "hard"]

    def validate_semantics(self) -> list[str]:
        errors: list[str] = []
        if self.answer_type == "refusal" and self.expected_evidence:
            errors.append(f"{self.id}: refusal items must not carry expected_evidence")
        if self.answer_type != "refusal" and not self.expected_evidence:
            errors.append(f"{self.id}: non-refusal items need >=1 evidence anchor")
        return errors
