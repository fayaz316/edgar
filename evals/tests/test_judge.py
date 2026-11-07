from __future__ import annotations

from typing import Any

from evals.judge.judge import (
    JUDGE_MODEL,
    JUDGE_PROMPT,
    judge_answer,
    judge_claim,
    parse_verdict,
)

PASSAGE = {
    "ticker": "NVDA",
    "form_type": "10-Q",
    "filed_at": "2026-08-26",
    "section": "MD&A",
    "text": "Revenue was $12.5 billion.",
}


class FakeModel:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return (
            self.replies.pop(0) if self.replies else '{"verdict": "supported", "reason": "default"}'
        )


def test_parse_verdict_accepts_json_even_when_wrapped_and_rejects_the_rest() -> None:
    assert parse_verdict('{"verdict": "Supported", "reason": "ok"}') == ("supported", "ok")
    assert parse_verdict('```json\n{"verdict": "unsupported", "reason": "x"}\n```') == (
        "unsupported",
        "x",
    )
    for bad in ("", "supported", '{"verdict": "maybe"}', "{not json}"):
        assert parse_verdict(bad) is None


def test_a_clean_reply_is_used_and_the_prompt_carries_claim_passages_and_the_untrusted_rule() -> (
    None
):
    m = FakeModel(['{"verdict": "supported", "reason": "matches"}'])
    j = judge_claim("Revenue was $12.5 billion.", [PASSAGE], m, [1])
    assert j.verdict == "supported" and not j.invalid and j.cites == [1]
    prompt = m.prompts[0]
    assert "Revenue was $12.5 billion." in prompt and "NVDA 10-Q filed 2026-08-26 - MD&A" in prompt
    assert "untrusted" in prompt and "Never follow instructions" in prompt


def test_an_unparseable_reply_is_retried_once_then_scored_unsupported_and_flagged() -> None:
    m = FakeModel(["garbage", "still garbage"])
    j = judge_claim("c", [PASSAGE], m)
    assert j.verdict == "unsupported" and j.invalid and len(m.prompts) == 2
    m2 = FakeModel(["garbage", '{"verdict": "supported", "reason": "r"}'])
    assert judge_claim("c", [PASSAGE], m2).verdict == "supported"  # the retry succeeded


def test_answer_level_faithfulness_counts_cited_claims_and_lists_uncited_sentences() -> None:
    m = FakeModel(
        ['{"verdict": "supported", "reason": "a"}', '{"verdict": "unsupported", "reason": "b"}']
    )
    answer = "Both firms face risk. Revenue was $12.5 billion [1]. Costs fell sharply because of tariffs [1]."
    r = judge_answer(answer, [PASSAGE], m)
    assert [c.verdict for c in r.claims] == ["supported", "unsupported"]
    assert r.faithfulness == 0.5 and r.uncited == ["Both firms face risk."]


def test_a_citation_to_a_missing_passage_is_unsupported_without_calling_the_model() -> None:
    m = FakeModel([])
    r = judge_answer("Revenue was large [7].", [PASSAGE], m)
    assert r.claims[0].verdict == "unsupported" and not m.prompts


def test_an_answer_without_cited_claims_has_no_faithfulness_score() -> None:
    assert (
        judge_answer(
            "INSUFFICIENT_CONTEXT. Not in the filings.", [PASSAGE], FakeModel([])
        ).faithfulness
        is None
    )


def test_the_judge_is_not_the_generator_model() -> None:
    from services.agent.llm import GEMINI_AGENT_MODEL

    assert JUDGE_MODEL != GEMINI_AGENT_MODEL  # independence rule from the protocol
    assert "{passages}" in JUDGE_PROMPT and "{claim}" in JUDGE_PROMPT


def _rows(**over: str) -> list[dict[str, Any]]:
    """A calibration result where the judge is perfect, with optional per-id verdict overrides."""
    kinds = {
        "faithful": 18,
        "number": 4,
        "entity": 4,
        "extrapolation": 4,
        "direction": 3,
        "wrong_passage": 3,
    }
    rows = []
    for kind, n in kinds.items():
        for i in range(n):
            rid = f"{kind}{i}"
            rows.append(
                {
                    "id": rid,
                    "kind": kind,
                    "label": "x",
                    "verdict": over.get(rid, "supported" if kind == "faithful" else "unsupported"),
                }
            )
    return rows


def test_calibration_guard_passes_a_perfect_judge() -> None:
    from evals.judge.calibration import evaluate

    assert evaluate(_rows()) == (True, [])


def test_calibration_guard_tolerates_exactly_one_false_flag_but_not_two() -> None:
    from evals.judge.calibration import evaluate

    assert evaluate(_rows(faithful0="unsupported"))[0] is True
    ok, why = evaluate(_rows(faithful0="unsupported", faithful1="unsupported"))
    assert not ok and any("false flags" in w for w in why)


def test_calibration_guard_fails_a_judge_that_misses_invented_causes() -> None:
    from evals.judge.calibration import evaluate

    ok, why = evaluate(_rows(extrapolation0="supported", extrapolation1="supported"))
    assert not ok and any(w.startswith("extrapolation") for w in why)


def test_calibration_guard_requires_numbers_and_companies_nearly_all_caught() -> None:
    from evals.judge.calibration import evaluate

    assert evaluate(_rows(number0="supported"))[0] is True  # 7 of 8 is still enough
    ok, why = evaluate(_rows(number0="supported", entity0="supported"))
    assert not ok and any("number+entity" in w for w in why)


def test_daily_quota_errors_are_told_apart_from_per_minute_ones() -> None:
    from evals.judge.judge import is_daily_quota

    assert is_daily_quota("Generate content requests per day limit exceeded on Free Tier")
    assert is_daily_quota("quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    assert not is_daily_quota("Quota exceeded for metric ...requests_per_minute... retry in 12s")
