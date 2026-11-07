# ADR 0013 — Bounded plan / act / verify agent loop over the tool registry (Phase 2)
Status: Accepted · Date: 2026-11-07

## Context
`/ask` retrieves once and answers once. Some questions need several searches (compare two companies,
two periods) or a retry after a bad tool call. Phase 2 asks for an agent loop with a step budget and
retry/repair, using the same tools as the MCP server (ADR 0012).

## Options considered
- **LangGraph state machine: plan -> act -> verify** (`services/agent/graph.py`). Explicit states,
  conditional edges, a recorded trace. **Won.** Honest note: at this size a plain `while` loop would
  also work; LangGraph is chosen because the project plan asks for it and it makes the states, limits and
  later streaming/checkpointing explicit. The price is one more dependency.
- **Plain loop, no framework** — simplest; no state-machine structure to inspect. Lost narrowly.
- **ReAct-style text parsing** — fragile; the model's native function calling is stricter. Lost.
- **Keep single-shot `/ask` only** — cannot do multi-search questions. Kept as is; the agent is additive.

## Decision
- `plan`: the model chooses tool calls or an answer. `act`: tool calls run through `ToolRegistry`; a
  failed call (bad arguments, unknown tool) goes back to the model as an observation so it can repair
  itself. `verify`: the answer's `[n]` citations are checked against the passages actually retrieved
  (the same `validate_answer` as `/ask`); a bad answer returns to `plan` with feedback.
- Bounded: 8 model turns, 8 tool calls, 2 repairs per question. Running out of any budget, or a failed
  model call, ends in `INSUFFICIENT_CONTEXT`, never a guess.
- Passages get one citation number per chunk across the whole run, so evidence from separate searches
  can be cited together.
- Every step is a `TraceEvent` (kind, detail, seconds, data). Gemini adapter (`GeminiLLM`) keeps the
  model's raw reply and echoes it back, because Gemini 3 requires its thought signatures in history.
- Entry point: `python -m services.agent.run "question"` prints the trace and answer.

## Evidence
- 13 unit tests with a scripted fake model (no API quota): grounded answer and trace shape, repair,
  repair limit, answering without searching, both budgets, recoverable tool errors, honest refusal,
  citation-number reuse, parallel calls, failing model, Gemini message conversion.
- Two real runs on Gemini (`gemini-3.1-flash-lite`): a two-company comparison made two parallel
  searches, answered in two model turns, and passed verify with 10 distinct cited passages; "What was
  Tesla's total revenue in 2025?" was refused in one turn without searching.

## Consequences
- **Not measured:** answer quality or faithfulness. n = 2 real runs is a smoke test, not an
  evaluation. The comparison answer cited a single passage for a paragraph of NVIDIA claims; whether
  each claim is supported was not checked.
- **Verify is shallow by design:** it checks that a citation points at a retrieved passage, not that the
  passage supports the sentence. A model can cite real passages for claims they do not support. Closing
  this is Phase 3 work (claim-level faithfulness checks).
- **Latency/quota:** the first model call took about 77 s in one run (free tier is 15 requests/minute;
  the adapter waits 20 s on a 429 and retries up to 3 times). Fine for a demo, not for users.
- **Drift risks:** the system prompt hard-codes the corpus (Apple, JPMorgan, NVIDIA) and the model id
  is a constant; both need to follow the corpus.
- **Phase 2 exit criterion is NOT met:** there is no UI trace view, no API endpoint for the agent, and
  the "contradiction hunter" sub-agent is not built.
- **Revisit trigger:** a held-out agent eval shows the loop no better than single-shot `/ask`, or the
  graph never uses more than one search (then the loop is ceremony).
