# ADR 0015 — Agent over HTTP with a streamed trace, and a single-file UI
Status: Accepted · Date: 2026-11-07

## Context
Phase 2's exit criterion is a multi-step query answered with the multi-tool trace visible in a UI. The agent
(ADR 0013) took a CLI. A run takes 5-80 seconds (free-tier rate limits), so a blocking page with a spinner would
hide exactly what we want to show.

## Options considered
- **Server-sent events over `POST /agent/stream` + a blocking `POST /agent`, and one static HTML page served by
  the gateway.** Trace steps appear as they happen. **Won.**
- **Blocking JSON only** — simplest; nothing visible for up to a minute. Lost.
- **Next.js app** — the project plan's Phase 6 target, and the right home for dashboards. Too heavy for this
  slice (build chain, second deployable); deferred to Phase 6.
- **Streamlit/Gradio** — quick, but ties the product to a framework UI we would replace. Lost.
- **WebSockets** — bidirectional; not needed for one-way progress. Lost.

## Decision
- `POST /agent/stream` emits `trace` events as the LangGraph runner produces them, then one `result` event
  (or an `error` event; a failure never leaves the client hanging). `POST /agent` returns the same data at once.
- A concurrency cap of 2 agent runs (`429` when busy) protects the free-tier Gemini quota.
- `GET /` serves `services/gateway/static/index.html`: question box, example questions, live trace with
  coloured step kinds and timings, the answer with clickable `[n]` citation chips, and the cited passages
  (click a chip to open and highlight its passage). Dark/light via the system setting; works at phone width.
- Untrusted text (model output, filing text) is only ever inserted with `textContent` / DOM nodes, never
  `innerHTML`; `**bold**` is the only markup interpreted, built from DOM nodes. A test asserts the page does not
  use `innerHTML`.
- Citations the answer makes but that were not retrieved stay plain text, never a link.

## Evidence
- 7 API tests with a scripted model: answer + citations + trace; refusal is a 200; event order and content type;
  unexpected failure becomes an `error` event; 422 on short/long questions; 429 when busy and slots released
  afterwards; page served.
- Real run in a browser: the supply-chain comparison question showed the model's two parallel searches
  arriving one by one with a spinner, then the answer with citation chips. A fake result containing
  `<img onerror>` and `<script>` rendered as plain text and executed nothing; the made-up citation `[9]`
  stayed plain text; clicking a chip opened and highlighted the passage. At 375 px wide there is no
  horizontal scroll. This found and fixed two real defects (raw `**bold**`, an empty bordered row).

## Consequences
- **No authentication and no per-user rate limit** (Phase 4): the endpoint spends the project's Gemini key, so it
  is for local/dev use only. It must not be exposed publicly as is.
- **Not verified:** behaviour behind Cloud Run or a proxy (the `x-accel-buffering: no` header is set, but
  streaming through a real deployment was not tested); browsers other than the in-app Chromium one.
- **UI limits:** one file with no framework will not grow gracefully; no history, no cancel button; it shows the
  cited passages only, not everything the agent retrieved; trace rows show a summary, not full tool payloads.
- **Revisit trigger:** Phase 6 (the Next.js app replaces this page; the API stays).
