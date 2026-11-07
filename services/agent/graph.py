"""The agent: a LangGraph state machine  plan -> act -> (plan ...) -> verify.

  plan    ask the model what to do next: call tools, or give an answer
  act     run the tool calls through the ToolRegistry; failures go back to the model as
          observations so it can repair its own arguments
  verify  check the answer's citations against the evidence actually retrieved; a bad answer
          sends the model back to plan with feedback (repair), up to a limit, then refuses

Bounded on purpose: at most `max_steps` model turns, `max_tool_calls` tool calls and
`max_repairs` repairs per question. Running out is a refusal, never a guess.
Every step is recorded in `trace` (the thing a user should be able to inspect).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from services.agent.claims import ClaimCheck, check_answer
from services.agent.llm import LLM, Message, ModelTurn
from services.gateway.answer import validate_answer
from services.tools.registry import ToolError, ToolRegistry

SYSTEM_PROMPT = """You are a research analyst answering questions about SEC filings (10-K and 10-Q)
for Apple, JPMorgan and NVIDIA, using tools.

How to work:
1. Use tools before stating any fact. search_filings returns numbered passages; list_filings
   shows which filings exist. Make several searches when the question needs them (for example
   one per company, or one per period) and compare.
2. Cite every factual sentence with the passage numbers returned by the tools, like [1] or [2][3].
   Cite only numbers the tools returned. Never invent numbers, dates, names or quotes.
3. If the filings do not contain the answer, reply exactly: INSUFFICIENT_CONTEXT, then one short
   sentence on what is missing.
4. If a tool returns an error, read it and retry with corrected arguments.
5. Be concise: 2-6 sentences unless the question needs more."""


@dataclass
class TraceEvent:
    kind: Literal["model", "tool", "verify", "budget", "error"]
    detail: str
    seconds: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)


class AgentState(TypedDict):
    question: str
    messages: list[Message]
    evidence: list[dict[str, Any]]  # passage n is evidence[n - 1]
    trace: list[TraceEvent]
    steps: int
    tool_calls: int
    repairs: int
    answer: str
    refused: bool
    cited: list[int]
    done: bool


@dataclass(frozen=True)
class AgentResult:
    answer: str
    refused: bool
    citations: list[dict[str, Any]]
    trace: list[TraceEvent]
    steps: int
    tool_calls: int
    repairs: int


def _refuse(state: AgentState, why: str, kind: Literal["budget", "error", "verify"]) -> AgentState:
    answer = f"INSUFFICIENT_CONTEXT — {why}"
    return {
        **state,
        "answer": answer,
        "refused": True,
        "cited": [],
        "done": True,
        "trace": [*state["trace"], TraceEvent(kind, why)],
    }


def build_graph(
    llm: LLM,
    registry: ToolRegistry,
    *,
    max_steps: int = 8,
    max_tool_calls: int = 8,
    max_repairs: int = 2,
    claim_check: Literal["off", "l1"] = "l1",
) -> Any:
    def plan(state: AgentState) -> AgentState:
        if state["steps"] >= max_steps:
            return _refuse(state, f"step budget of {max_steps} model turns exhausted", "budget")
        start = time.perf_counter()
        try:
            turn = llm.generate(SYSTEM_PROMPT, state["messages"], registry.specs())
        except Exception as exc:  # the model is an external dependency; fail closed
            return _refuse(state, f"the model call failed ({str(exc)[:120]})", "error")
        names = ", ".join(c.name for c in turn.tool_calls)
        detail = f"calls: {names}" if turn.tool_calls else f"answer: {turn.text[:80]!r}"
        event = TraceEvent("model", detail, time.perf_counter() - start)
        return {
            **state,
            "messages": [*state["messages"], Message("model", turn=turn)],
            "steps": state["steps"] + 1,
            "trace": [*state["trace"], event],
        }

    def after_plan(state: AgentState) -> str:
        if state["done"]:
            return END
        last = state["messages"][-1].turn
        return "act" if last and last.tool_calls else "verify"

    def act(state: AgentState) -> AgentState:
        turn = state["messages"][-1].turn or ModelTurn()
        messages = list(state["messages"])
        evidence = list(state["evidence"])
        trace = list(state["trace"])
        used = state["tool_calls"]
        for call in turn.tool_calls:
            start = time.perf_counter()
            if used >= max_tool_calls:
                result: dict[str, Any] = {
                    "error": f"tool-call budget of {max_tool_calls} used up; answer from the "
                    "passages you already have, or reply INSUFFICIENT_CONTEXT"
                }
            else:
                used += 1
                try:
                    result = _number_passages(registry.call(call.name, call.args), evidence)
                except ToolError as exc:
                    result = {"error": str(exc)}
            ok = "error" not in result
            summary = (
                (f"{len(result.get('passages', []))} passages" if "passages" in result else "ok")
                if ok
                else f"ERROR {result['error'][:90]}"
            )
            trace.append(
                TraceEvent(
                    "tool",
                    f"{call.name}({_short(call.args)}) -> {summary}",
                    time.perf_counter() - start,
                    {"tool": call.name, "args": call.args, "ok": ok},
                )
            )
            messages.append(Message("tool", tool_name=call.name, result=result))
        return {
            **state,
            "messages": messages,
            "evidence": evidence,
            "trace": trace,
            "tool_calls": used,
        }

    def verify(state: AgentState) -> AgentState:
        text = (state["messages"][-1].turn or ModelTurn()).text
        checked = validate_answer(text, n_passages=len(state["evidence"]))
        model_refused = text.strip().upper().startswith("INSUFFICIENT_CONTEXT")
        if not model_refused and not checked.refused and claim_check == "l1":
            bad = [c for c in check_answer(text, state["evidence"]) if c.l1_unsupported]
            if bad:
                return _reject(state, _l1_problem(bad), max_repairs)
        if model_refused or not checked.refused:
            event = TraceEvent(
                "verify",
                "refused by the model"
                if model_refused
                else f"ok, cites passages {checked.cited_passages}",
            )
            return {
                **state,
                "answer": checked.answer,
                "refused": checked.refused,
                "cited": checked.cited_passages,
                "done": True,
                "trace": [*state["trace"], event],
            }
        problem = (
            f"it cites passages that were not retrieved: {checked.dangling_citations}"
            if checked.dangling_citations
            else "it has no valid [n] citations (search first, then cite what you found)"
        )
        return _reject(state, problem, max_repairs)

    def after_verify(state: AgentState) -> str:
        return END if state["done"] else "plan"

    graph = StateGraph(AgentState)
    graph.add_node("plan", plan)
    graph.add_node("act", act)
    graph.add_node("verify", verify)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", after_plan, {"act": "act", "verify": "verify", END: END})
    graph.add_edge("act", "plan")
    graph.add_conditional_edges("verify", after_verify, {"plan": "plan", END: END})
    return graph.compile()


def _l1_problem(bad: list[ClaimCheck]) -> str:
    parts = []
    for c in bad[:3]:
        what = []
        if c.missing_numbers:
            what.append(f"figures not in the cited passages {c.missing_numbers}")
        if c.missing_companies:
            what.append(f"company not among the cited passages {c.missing_companies}")
        parts.append(f'"{c.text[:70]}" ({"; ".join(what)})')
    return "some claims are not grounded in what they cite: " + " | ".join(parts)


def _reject(state: AgentState, problem: str, max_repairs: int) -> AgentState:
    """Send a bad answer back to `plan` with feedback, or refuse once repairs are used up."""
    if state["repairs"] >= max_repairs:
        return _refuse(state, f"the answer could not be grounded ({problem})", "verify")
    feedback = (
        f"Your answer was rejected: {problem}. State figures exactly as they appear in the "
        "passages you cite (do not state computed or rounded values), name only the company "
        "whose passage you cite, and cite only passage numbers the tools returned, as [n]. "
        "Search again if you need more evidence, or reply INSUFFICIENT_CONTEXT."
    )
    return {
        **state,
        "messages": [*state["messages"], Message("user", text=feedback)],
        "repairs": state["repairs"] + 1,
        "trace": [*state["trace"], TraceEvent("verify", f"rejected: {problem}")],
    }


def _short(args: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items() if v is not None)[:110]


def _number_passages(result: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Give each retrieved passage a stable citation number (same chunk -> same number)."""
    if "passages" not in result:
        return result
    known = {p["chunk_id"]: i + 1 for i, p in enumerate(evidence)}
    numbered: list[dict[str, Any]] = []
    for p in result["passages"]:
        n = known.get(p["chunk_id"])
        if n is None:
            evidence.append(p)
            n = known[p["chunk_id"]] = len(evidence)
        numbered.append({"passage": n, **{k: v for k, v in p.items() if k != "chunk_id"}})
    return {"passages": numbered, "note": "cite a passage as [n] using its 'passage' number"}


def stream_agent(
    question: str,
    llm: LLM,
    registry: ToolRegistry,
    *,
    max_steps: int = 8,
    max_tool_calls: int = 8,
    max_repairs: int = 2,
    claim_check: Literal["off", "l1"] = "l1",
) -> Iterator[TraceEvent | AgentResult]:
    """Run the agent, yielding each TraceEvent as soon as it happens, then the AgentResult last."""
    graph = build_graph(
        llm,
        registry,
        max_steps=max_steps,
        max_tool_calls=max_tool_calls,
        max_repairs=max_repairs,
        claim_check=claim_check,
    )
    initial: AgentState = {
        "question": question,
        "messages": [Message("user", text=question)],
        "evidence": [],
        "trace": [],
        "steps": 0,
        "tool_calls": 0,
        "repairs": 0,
        "answer": "",
        "refused": False,
        "cited": [],
        "done": False,
    }
    seen = 0
    final = initial
    config = {"recursion_limit": 4 * (max_steps + max_repairs) + 10}
    for state in graph.stream(initial, config, stream_mode="values"):
        final = state
        yield from state["trace"][seen:]
        seen = len(state["trace"])
    yield _to_result(final)


def _to_result(final: AgentState) -> AgentResult:
    citations = [
        {
            "passage": n,
            **{k: v for k, v in final["evidence"][n - 1].items() if k != "text"},
            "excerpt": final["evidence"][n - 1]["text"][:200],
            "text": final["evidence"][n - 1]["text"],
        }
        for n in final["cited"]
    ]
    return AgentResult(
        answer=final["answer"],
        refused=final["refused"],
        citations=citations,
        trace=final["trace"],
        steps=final["steps"],
        tool_calls=final["tool_calls"],
        repairs=final["repairs"],
    )


def run_agent(
    question: str,
    llm: LLM,
    registry: ToolRegistry,
    *,
    max_steps: int = 8,
    max_tool_calls: int = 8,
    max_repairs: int = 2,
    claim_check: Literal["off", "l1"] = "l1",
) -> AgentResult:
    result: AgentResult | None = None
    for item in stream_agent(
        question,
        llm,
        registry,
        max_steps=max_steps,
        max_tool_calls=max_tool_calls,
        max_repairs=max_repairs,
        claim_check=claim_check,
    ):
        if isinstance(item, AgentResult):
            result = item
    assert result is not None  # stream_agent always ends with the result
    return result
