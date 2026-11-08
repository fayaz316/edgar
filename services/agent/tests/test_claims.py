from __future__ import annotations

from services.agent.claims import (
    check_answer,
    companies_in,
    numbers_in,
    passage_numbers,
    split_claims,
)


class FakeNli:
    """Entails iff every word of the hypothesis appears in the premise (a stand-in, not a model)."""

    def entail_prob(self, premise: str, hypothesis: str) -> float:
        words = [w.strip(".,").lower() for w in hypothesis.split()]
        return 1.0 if all(w in premise.lower() for w in words) else 0.0


def test_split_handles_citation_placement_bullets_and_abbreviations() -> None:
    answer = (
        "Revenue rose to $1.9 trillion in the U.S. market [1]. Costs fell. [2]\n"
        "* **Risk:** supply is concentrated [3]"
    )
    assert split_claims(answer) == [
        ("Revenue rose to $1.9 trillion in the U.S. market.", [1]),
        ("Costs fell.", [2]),
        ("Risk: supply is concentrated", [3]),
    ]


def test_numbers_ignore_form_names_small_ints_and_citations() -> None:
    assert numbers_in("The 10-K for Q3 lists 3 segments and $1,250.5 million [4], up 12%") == {
        "1250.5",
        "12",
    }
    assert numbers_in("a $5 charge and 7%") == {"5", "7"}  # small ints kept when $ or % attached
    assert passage_numbers("5.0 billion, 49%, 2,114") == {"5.0", "49", "2114"}


def test_companies_are_found_by_name() -> None:
    assert companies_in("Apple and JPMorganChase differ; NVIDIA too") == {"AAPL", "JPM", "NVDA"}
    assert companies_in("the Firm reported") == set()


EVIDENCE = [
    {"ticker": "NVDA", "text": "NVIDIA revenue was $12.5 billion in the quarter, up 30%."},
    {"ticker": "AAPL", "text": "The Company repurchased shares."},
]


def test_l1_flags_a_number_the_passage_does_not_contain() -> None:
    [c] = check_answer("NVIDIA revenue was $13.5 billion [1].", EVIDENCE)
    assert c.missing_numbers == ["13.5"] and c.unsupported and c.l1_unsupported


def test_l1_flags_a_company_not_among_the_cited_passages() -> None:
    [c] = check_answer("Apple revenue was $12.5 billion [1].", EVIDENCE)
    assert c.missing_companies == ["AAPL"] and c.unsupported


def test_grounded_claim_passes_both_layers() -> None:
    [c] = check_answer("NVIDIA revenue was $12.5 billion, up 30% [1].", EVIDENCE, FakeNli())
    assert not c.unsupported and c.entailment == 1.0


def test_l2_flags_a_claim_the_passage_does_not_entail() -> None:
    [c] = check_answer(
        "NVIDIA revenue was $12.5 billion because of tariffs [1].", EVIDENCE, FakeNli()
    )
    assert not c.l1_unsupported and c.l2_unsupported and c.unsupported


def test_best_of_several_cited_passages_counts() -> None:
    [c] = check_answer("The Company repurchased shares [1][2].", EVIDENCE, FakeNli())
    assert c.cites == [1, 2] and not c.unsupported


def test_uncited_sentences_are_reported_not_rejected() -> None:
    checks = check_answer(
        "Both firms face risk. NVIDIA revenue was $12.5 billion [1].", EVIDENCE, FakeNli()
    )
    assert checks[0].uncited and not checks[0].unsupported
    assert not checks[1].unsupported


def test_citation_to_a_nonexistent_passage_is_unsupported() -> None:
    [c] = check_answer("Revenue was large [9].", EVIDENCE)
    assert c.unsupported


def test_comma_form_citations_are_claims_with_cites_not_uncited_sentences() -> None:
    assert split_claims("NVIDIA leads in AI [12, 14, 15].") == [
        ("NVIDIA leads in AI.", [12, 14, 15])
    ]
    assert split_claims("It grew. [1, 2] Next point [3].") == [
        ("It grew.", [1, 2]),
        ("Next point.", [3]),
    ]


def test_l1_applies_to_comma_form_citations_too() -> None:
    evidence = [{"ticker": "NVDA", "text": "NVIDIA revenue was $12.5 billion."}] * 2
    [c] = check_answer("NVIDIA revenue was $13.5 billion [1, 2].", evidence)
    assert c.cites == [1, 2] and c.missing_numbers == ["13.5"]
