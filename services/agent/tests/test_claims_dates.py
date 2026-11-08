"""Date-aware L1 grounding (spec: evals/claims/L1_DATES.md)."""

from __future__ import annotations

from typing import Any

from services.agent.claims import (
    check_answer,
    ground_claim,
    known_dates,
    parse_metadata_dates,
    passage_facts,
    scan_dates,
)

NONE = parse_metadata_dates([])


def _keys(text: str) -> list[tuple[int | None, int | None, int | None]]:
    return [k for _, k in scan_dates(text)[0]]


def test_scan_dates_reads_the_common_formats_and_abbreviations() -> None:
    assert _keys("July 26, 2026") == [(2026, 7, 26)]
    assert _keys("Apr 26, 2026 and 27 September 2025") == [(2026, 4, 26), (2025, 9, 27)]
    assert _keys("filed 2026-08-26, due 9/30/2026") == [(2026, 8, 26), (2026, 9, 30)]
    assert _keys("In May 2026 and on June 5") == [(2026, 5, None), (None, 6, 5)]
    assert _keys("Sept. 30th, 2026") == [(2026, 9, 30)]


def test_scan_dates_blanks_what_it_matched_and_ignores_lowercase_may() -> None:
    found, rest = scan_dates("As of July 26, 2026, revenue was $5.0 billion")
    assert len(found) == 1 and "26" not in rest and "5.0" in rest
    assert scan_dates("it may 20 times exceed")[0] == []  # a verb, not the month


def test_a_dates_digits_do_not_count_as_amounts_in_a_passage() -> None:
    known, amounts = passage_facts(
        "As of April 26, 2026, expense was $ 20.8 billion over 2.6 years."
    )
    assert amounts == {"20.8", "2.6"}  # not '26', not '2026'
    assert known.full == {(2026, 4, 26)} and 2026 in known.years


def test_metadata_grounds_a_date_but_never_an_amount() -> None:
    passage = [{"text": "Expense was $ 20.8 billion."}]
    meta = parse_metadata_dates(["2026-05-20"])
    assert ground_claim("The filing of May 20, 2026 reports $20.8 billion.", passage, meta) == (
        [],
        [],
    )
    dates, amounts = ground_claim("Expense rose 20% in the filing of May 20, 2026.", passage, meta)
    assert dates == [] and amounts == ["20"]  # the day-of-month cannot launder a percentage


def test_without_metadata_a_filing_date_not_in_the_passage_is_flagged() -> None:
    dates, _ = ground_claim(
        "The filing of May 20, 2026 reports $20.8 billion.",
        [{"text": "Expense was $ 20.8 billion."}],
        NONE,
    )
    assert dates == ["May 20, 2026"]


def test_a_right_day_wrong_month_date_is_caught_even_though_the_digits_exist() -> None:
    passage = [{"text": "As of July 26, 2026, commitments were $ 25 billion."}]
    assert ground_claim("As of June 26, 2026, commitments were $25 billion.", passage, NONE)[0] == [
        "June 26, 2026"
    ]
    assert ground_claim("As of July 26, 2026, commitments were $25 billion.", passage, NONE) == (
        [],
        [],
    )


def test_partial_dates_are_matched_on_the_parts_they_state() -> None:
    meta = known_dates([(2026, 5, 20)])
    passage = [{"text": "x"}]
    assert ground_claim("In its May 2026 filing it said so.", passage, meta)[0] == []
    assert ground_claim("In its June 2026 filing it said so.", passage, meta)[0] == ["June 2026"]


def test_abbreviated_passage_dates_ground_full_month_names_in_the_claim() -> None:
    assert ground_claim(
        "As of April 26, 2026 it held 5.5 million shares.",
        [{"text": "Balance as of Apr 26, 2026 | 5.5 million"}],
        NONE,
    ) == ([], [])


def test_bare_years_need_the_passage_or_metadata() -> None:
    assert ground_claim(
        "In fiscal year 2027 it grew.", [{"text": "fiscal year 2027 results"}], NONE
    ) == ([], [])
    assert ground_claim(
        "In fiscal year 2031 it grew.", [{"text": "fiscal year 2027 results"}], NONE
    )[1] == ["2031"]


def test_the_real_failure_check_answer_accepts_a_metadata_date_the_passage_lacks() -> None:
    evidence = [
        {"ticker": "NVDA", "text": "On May 15, 2026, we issued 926,447 shares to key employees."}
    ]
    answer = (
        "NVIDIA's report for the period ended July 26, 2026 shows 926,447 shares were issued [1]."
    )
    [flagged] = check_answer(answer, evidence)
    assert flagged.missing_dates == ["July 26, 2026"]  # without metadata: the old false reject
    [ok] = check_answer(answer, evidence, metadata_dates=["2026-07-26", "2026-08-26"])
    assert not ok.l1_unsupported


def test_agent_collects_dates_from_list_filings_and_lets_the_answer_use_them() -> None:
    from services.agent.graph import run_agent
    from services.agent.llm import ModelTurn, ToolCall
    from services.agent.tests.test_agent import FakeRetriever, ScriptedLLM
    from services.tools.filings import ToolContext, build_registry
    from services.tools.tests.test_registry import _Pool

    pool = _Pool([("NVDA", "10-Q", "0001045810-26-000075", "2026-07-26", "2026-08-26")])
    registry = build_registry(ToolContext(retriever=FakeRetriever(), pool=pool))  # type: ignore[arg-type]
    llm: Any = ScriptedLLM(
        [
            ModelTurn(tool_calls=(ToolCall("list_filings", {"ticker": "NVDA"}),)),
            ModelTurn(tool_calls=(ToolCall("search_filings", {"query": "export controls text"}),)),
            ModelTurn(
                text="For the period ended July 26, 2026, export controls text is disclosed [1]."
            ),
        ]
    )
    r = run_agent("q", llm, registry)
    assert (
        not r.refused and r.repairs == 0
    )  # the metadata date is accepted, not repaired into a refusal
