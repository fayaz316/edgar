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


def _row(
    kind: str, refused: bool, verdicts: list[str], infra: bool = False, uncited: int = 0
) -> dict[str, Any]:
    claims = [{"text": "c", "verdict": v, "reason": "", "invalid": False} for v in verdicts]
    faith = (sum(v == "supported" for v in verdicts) / len(verdicts)) if verdicts else None
    return {
        "id": "q",
        "kind": kind,
        "refused": refused,
        "infra_error": infra,
        "claims": claims,
        "uncited": ["u"] * uncited,
        "faithfulness": faith,
    }


def test_summary_scores_answers_and_checks_refusals_separately() -> None:
    from evals.judge.run_answers import summarize

    rows = [
        _row("answerable", False, ["supported", "supported"]),
        _row("answerable", False, ["supported", "unsupported"], uncited=2),
        _row(
            "answerable", True, []
        ),  # the agent declined an answerable question: not scored for faithfulness
        _row("unanswerable", True, []),
        _row("unanswerable", False, ["unsupported"]),  # answered when it should have refused
    ]
    s = summarize(rows)
    assert s["answerable"]["n"] == 3 and s["answerable"]["answered"] == 2
    assert s["answerable"]["claims_judged"] == 4 and s["answerable"]["claims_supported"] == 3
    assert s["answerable"]["mean_answer_faithfulness"] == 0.75
    assert (
        s["answerable"]["answers_with_an_unsupported_claim"] == 1
        and s["answerable"]["uncited_sentences"] == 2
    )
    assert s["unanswerable"] == {"n": 2, "refused_correctly": 1, "answered_instead": ["q"]}


def test_a_refusal_caused_by_a_failed_model_call_is_not_counted_as_a_correct_refusal() -> None:
    from evals.judge.run_answers import summarize

    s = summarize([_row("unanswerable", True, [], infra=True), _row("unanswerable", True, [])])
    assert (
        s["infra_errors"] == 1
        and s["unanswerable"]["n"] == 1
        and s["unanswerable"]["refused_correctly"] == 1
    )


def test_evidence_is_rebuilt_by_citation_number_for_the_judge() -> None:
    from evals.judge.run_answers import evidence_from_citations

    ev = evidence_from_citations([{"passage": 3, "text": "c"}, {"passage": 1, "text": "a"}])
    assert [e.get("text") for e in ev] == ["a", None, "c"]
    assert evidence_from_citations([]) == []


def test_server_errors_are_told_apart_from_client_errors() -> None:
    from evals.judge.judge import is_transient_server_error

    class E(Exception):
        def __init__(self, code: int) -> None:
            self.code = code

    assert is_transient_server_error(E(503)) and is_transient_server_error(E(500))
    assert not is_transient_server_error(E(429)) and not is_transient_server_error(E(400))
    assert not is_transient_server_error(ValueError("no code"))


def _inf_rows(a_faith: float, b_faith: float, **over: Any) -> list[dict[str, Any]]:
    rows = []
    for i in range(8):
        for v, f in (("v1", a_faith), ("v2", b_faith)):
            rows.append(
                {
                    "id": f"q{i}",
                    "variant": v,
                    "refused": False,
                    "infra": False,
                    "loose": [],
                    "faithfulness": f,
                }
            )
    for r in rows:
        r.update({k: val for k, val in over.items() if r["variant"] == "v2"})
    return rows


def test_inference_guard_adopts_only_with_a_real_gain_and_a_clean_injection_regression() -> None:
    from evals.claims.run_inference import guard

    good_inj = {"v2": {"attacks": [{"success": False}] * 8, "utility": 1.0}}
    assert guard(_inf_rows(0.87, 0.93), good_inj) == (True, [])
    ok, why = guard(_inf_rows(0.87, 0.89), good_inj)
    assert not ok and any("faithfulness" in w for w in why)  # below +0.03 and below 0.90
    ok, why = guard(_inf_rows(0.87, 0.93), None)
    assert not ok and any("injection regression" in w for w in why)
    bad_inj = {"v2": {"attacks": [{"success": True}] + [{"success": False}] * 7, "utility": 1.0}}
    assert not guard(_inf_rows(0.87, 0.93), bad_inj)[0]
    assert not guard(_inf_rows(0.87, 0.93, loose=["an uncited claim"]), good_inj)[0]
