from __future__ import annotations

from typing import Any

from services.agent.graph import run_agent
from services.agent.llm import LLM, Message, ModelTurn, ToolCall, to_contents
from services.gateway.retrieval import RetrievedChunk
from services.tools.filings import ToolContext, build_registry
from services.tools.tests.test_registry import _Pool


def _chunk(cid: int, ticker: str = "NVDA", text: str = "export controls text") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid,
        ticker=ticker,
        form_type="10-Q",
        filed_at="2026-08-26",
        section="Risk Factors",
        text=text,
        rrf_score=0.1,
        lexical_rank=1,
        semantic_rank=1,
        accession=f"acc-{cid}",
    )


class FakeRetriever:
    """Returns the same chunk ids for every query unless `by_query` says otherwise."""

    def __init__(self, ids: list[int] | None = None, by_query: dict[str, list[int]] | None = None):
        self.ids = ids or [11]
        self.by_query = by_query or {}

    def retrieve(self, query: str, **_: Any) -> list[RetrievedChunk]:
        return [_chunk(i) for i in self.by_query.get(query, self.ids)]


class ScriptedLLM:
    """Plays back ModelTurns in order and records what it was shown."""

    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.seen: list[list[Message]] = []

    def generate(
        self, system: str, messages: list[Message], tools: list[dict[str, Any]]
    ) -> ModelTurn:
        self.seen.append(list(messages))
        return self.turns.pop(0) if self.turns else ModelTurn(text="(script exhausted)")


def _registry(retriever: FakeRetriever | None = None) -> Any:
    ctx = ToolContext(retriever=retriever or FakeRetriever(), pool=_Pool([]))  # type: ignore[arg-type]
    return build_registry(ctx)


def _search(query: str = "export controls", **kw: Any) -> ModelTurn:
    return ModelTurn(tool_calls=(ToolCall("search_filings", {"query": query, **kw}),))


def _llm(turns: list[ModelTurn]) -> LLM:
    return ScriptedLLM(turns)


def test_search_then_grounded_answer_records_a_full_trace() -> None:
    llm = _llm([_search(), ModelTurn(text="Export controls hurt demand [1].")])
    r = run_agent("q", llm, _registry())
    assert not r.refused and r.answer.endswith("[1].")
    assert [e.kind for e in r.trace] == ["model", "tool", "model", "verify"]
    assert r.steps == 2 and r.tool_calls == 1 and r.repairs == 0
    assert [c["passage"] for c in r.citations] == [1] and r.citations[0]["ticker"] == "NVDA"


def test_dangling_citation_triggers_one_repair_then_succeeds() -> None:
    llm = _llm([_search(), ModelTurn(text="Claim [5]."), ModelTurn(text="Fixed claim [1].")])
    r = run_agent("q", llm, _registry())
    assert not r.refused and r.repairs == 1
    assert [e.kind for e in r.trace if e.kind == "verify"] == ["verify", "verify"]
    assert "rejected" in r.trace[3].detail


def test_still_ungrounded_after_the_repair_limit_refuses() -> None:
    bad = ModelTurn(text="Claim [9].")
    r = run_agent("q", _llm([_search(), bad, bad, bad]), _registry(), max_repairs=2)
    assert r.refused and r.answer.startswith("INSUFFICIENT_CONTEXT")
    assert r.repairs == 2 and r.citations == []


def test_answering_without_searching_is_rejected_and_repaired() -> None:
    llm = ScriptedLLM(
        [ModelTurn(text="From memory, 42%."), _search(), ModelTurn(text="Found it [1].")]
    )
    r = run_agent("q", llm, _registry())
    assert not r.refused and r.repairs == 1 and r.tool_calls == 1
    feedback = [m for m in llm.seen[1] if m.role == "user"][-1].text
    assert "no valid [n] citations" in feedback


def test_step_budget_stops_a_looping_model() -> None:
    r = run_agent("q", _llm([_search()] * 20), _registry(), max_steps=3)
    assert r.refused and "step budget" in r.answer
    assert r.steps == 3 and r.trace[-1].kind == "budget"


def test_tool_call_budget_hands_back_an_error_not_more_data() -> None:
    llm = ScriptedLLM([_search("query a"), _search("query b"), ModelTurn(text="Done [1].")])
    r = run_agent("q", llm, _registry(), max_tool_calls=1)
    assert r.tool_calls == 1
    last_tool = [m for m in llm.seen[2] if m.role == "tool"][-1]
    assert "budget" in last_tool.result["error"]


def test_a_tool_error_is_shown_to_the_model_so_it_can_repair() -> None:
    bad = ModelTurn(
        tool_calls=(ToolCall("search_filings", {"query": "export", "form_type": "8-K"}),)
    )
    llm = ScriptedLLM([bad, _search(), ModelTurn(text="ok [1].")])
    r = run_agent("q", llm, _registry())
    assert not r.refused and r.tool_calls == 2
    tool_msgs = [m for m in llm.seen[1] if m.role == "tool"]
    assert "invalid arguments" in tool_msgs[0].result["error"]
    tool_events = [e for e in r.trace if e.kind == "tool"]
    assert [e.data["ok"] for e in tool_events] == [False, True]


def test_unknown_tool_is_also_recoverable() -> None:
    llm = ScriptedLLM(
        [ModelTurn(tool_calls=(ToolCall("shell", {}),)), _search(), ModelTurn(text="ok [1].")]
    )
    r = run_agent("q", llm, _registry())
    assert not r.refused
    assert "unknown tool" in next(m for m in llm.seen[1] if m.role == "tool").result["error"]


def test_the_model_may_refuse_honestly_without_being_second_guessed() -> None:
    r = run_agent(
        "q", _llm([_search(), ModelTurn(text="INSUFFICIENT_CONTEXT — no data.")]), _registry()
    )
    assert r.refused and r.repairs == 0 and r.trace[-1].detail == "refused by the model"


def test_same_chunk_from_two_searches_keeps_one_citation_number() -> None:
    retriever = FakeRetriever(by_query={"query a": [11, 12], "query b": [12, 13]})
    llm = ScriptedLLM([_search("query a"), _search("query b"), ModelTurn(text="x [2][3].")])
    r = run_agent("q", llm, _registry(retriever))
    second = [m for m in llm.seen[2] if m.role == "tool"][-1].result["passages"]
    assert [p["passage"] for p in second] == [2, 3]  # chunk 12 reused number 2; chunk 13 is new
    assert sorted(c["passage"] for c in r.citations) == [2, 3]


def test_parallel_tool_calls_in_one_turn_are_all_answered() -> None:
    two = ModelTurn(
        tool_calls=(ToolCall("search_filings", {"query": "query a"}), ToolCall("list_filings", {}))
    )
    llm = ScriptedLLM([two, ModelTurn(text="ok [1].")])
    r = run_agent("q", llm, _registry())
    assert r.tool_calls == 2 and sum(1 for m in llm.seen[1] if m.role == "tool") == 2


def test_a_failing_model_call_fails_closed() -> None:
    class Boom:
        def generate(self, *a: Any, **k: Any) -> ModelTurn:
            raise RuntimeError("quota exceeded")

    r = run_agent("q", Boom(), _registry())
    assert r.refused and "model call failed" in r.answer and r.trace[-1].kind == "error"


def test_to_contents_groups_consecutive_tool_results_into_one_turn() -> None:
    turn = ModelTurn(tool_calls=(ToolCall("a", {"x": 1}), ToolCall("b", {})))
    contents = to_contents(
        [
            Message("user", text="hi"),
            Message("model", turn=turn),
            Message("tool", tool_name="a", result={"r": 1}),
            Message("tool", tool_name="b", result={"r": 2}),
        ]
    )
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert len(contents[1].parts) == 2 and len(contents[2].parts) == 2


def _numeric_retriever() -> FakeRetriever:
    class R(FakeRetriever):
        def retrieve(self, query: str, **_: Any) -> list[RetrievedChunk]:
            return [
                _chunk(21, text="NVIDIA revenue was $12.5 billion, up 30% from a year earlier.")
            ]

    return R()


def test_l1_rejects_a_figure_the_cited_passage_does_not_contain_then_repairs() -> None:
    llm = ScriptedLLM(
        [
            _search(),
            ModelTurn(text="NVIDIA revenue was $13.5 billion [1]."),
            ModelTurn(text="NVIDIA revenue was $12.5 billion [1]."),
        ]
    )
    r = run_agent("q", llm, _registry(_numeric_retriever()))
    assert not r.refused and r.repairs == 1 and "12.5" in r.answer
    rejected = [e for e in r.trace if e.kind == "verify" and e.detail.startswith("rejected")]
    assert "13.5" in rejected[0].detail


def test_l1_rejects_a_company_that_is_not_among_the_cited_passages() -> None:
    llm = ScriptedLLM(
        [
            _search(),
            ModelTurn(text="Apple revenue was $12.5 billion [1]."),
            ModelTurn(text="NVIDIA revenue was $12.5 billion [1]."),
        ]
    )
    r = run_agent("q", llm, _registry(_numeric_retriever()))
    assert not r.refused and r.repairs == 1


def test_l1_gives_up_after_the_repair_limit() -> None:
    bad = ModelTurn(text="NVIDIA revenue was $99 billion [1].")
    r = run_agent("q", ScriptedLLM([_search(), bad, bad, bad]), _registry(_numeric_retriever()))
    assert r.refused and "could not be grounded" in r.answer and r.repairs == 2


def test_claim_check_off_keeps_the_old_behaviour() -> None:
    llm = ScriptedLLM([_search(), ModelTurn(text="NVIDIA revenue was $13.5 billion [1].")])
    r = run_agent("q", llm, _registry(_numeric_retriever()), claim_check="off")
    assert not r.refused and r.repairs == 0


class SlowLLM(ScriptedLLM):
    def generate(
        self, system: str, messages: list[Message], tools: list[dict[str, Any]]
    ) -> ModelTurn:
        import time

        time.sleep(0.05)
        return super().generate(system, messages, tools)


def test_wall_clock_deadline_stops_a_slow_run_between_steps() -> None:
    r = run_agent("q", SlowLLM([_search()] * 10), _registry(), max_seconds=0.02)
    assert r.refused and "time budget" in r.answer and r.trace[-1].kind == "budget"
    assert r.steps == 1  # one model call completed, the next plan step refused to start


def test_no_deadline_by_default() -> None:
    r = run_agent("q", _llm([_search(), ModelTurn(text="ok [1].")]), _registry())
    assert not r.refused
