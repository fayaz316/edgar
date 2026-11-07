# ADR 0017 — Security hardening: API keys, limits, browser protections, injection defence
Status: Accepted · Date: 2026-11-08 · Threat model: `docs/security/threat-model.md` (written first)

## Context
`/agent` and `/ask` spend the project's Gemini key and were open to anyone. Filings are third-party text, so a retrieved
passage can carry instructions aimed at the model. Phase 4 asks for authentication, limits, guardrails and an injection test.

## Options considered
- **API keys (hashed, constant-time)** vs **JWT/sessions.** Keys identify a caller with the least machinery and suit a
  single-tenant service and scripts. JWT/sessions are for end-user identity; not needed yet. **Keys won.**
- **In-memory rate limiter** vs **Redis / an API gateway.** In-memory is testable and dependency-free but per instance. **In-memory
  won for now**, with the limit stated.
- **Strict CSP (no inline script/style)** vs a permissive one. Strict required splitting the UI into `app.js` / `app.css`. **Strict won.**
- **Prompt hardening (v1) vs leaving the prompt as is (v0)** decided by a pre-registered experiment (below), not by taste.
- **Secret Manager, least-privilege service accounts, IAP/WAF**: need a Terraform apply and cost approval. **Not done.**

## Decision (what was built)
- Keys: `ea_` + 256 random bits, shown once (`python -m services.gateway.keys NAME`), only the SHA-256 in `EA_API_KEYS`; comparison
  never exits early; keys are never logged (test). `/ask`, `/agent`, `/agent/stream` need one; health and the UI stay public.
  Production fails closed without keys; `EA_AUTH=off` is rejected outside `EA_ENVIRONMENT=dev`; a missing security setup is a 500, not an open door.
- Limits: per-key sliding window (default 20/min), per-key daily agent-run cap (200), failed-auth throttle per client address
  (10 failures in 5 minutes), the existing 2-run concurrency cap, question length cap, step/tool/repair limits and a wall-clock
  deadline checked between agent steps.
- Browser: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` everywhere; strict CSP on the UI; API docs disabled in
  production; the UI keeps the key in `sessionStorage` only.
- Logging: question text is no longer logged (length and a short hash only).
- Injection: the hardened prompt (security rules + an "untrusted data" note on every tool result) is now the default.

## Evidence
- 204 tests pass, including 15 new auth/limit/header tests that go through the real HTTP stack.
- Against a running server: no key or a wrong key gives 401; health and UI stay public; the headers and CSP are present; a valid key
  runs the agent. In a real browser: an injected inline `<script>` was blocked by the CSP and reported as a violation; a wrong key shows
  a clear message; the right key works.
- **Prompt-injection experiment** (`evals/injection/`, protocol and criteria written before any run; one run per variant, temperature 0):

  | Variant | Attacks that succeeded | Benign questions answered with citations |
  |---|---|---|
  | v0 (original prompt) | **2 of 8** (instruction override, "note to the AI assistant": both made the model add the planted token) | 3 of 3 |
  | v1 (security rules) | **0 of 8** | 3 of 3 |

  Under v0 the answers also cited the injected passage as evidence; under v1 they cited only the genuine passage. Per the
  pre-registered rule (adopt v1 unless it is worse on either measure), v1 is the default.
- A dependency audit (`pip-audit` on the locked runtime dependencies) reported no known vulnerabilities.

## Consequences
- **The injection result is weak evidence:** eight hand-written attacks, one run each, one model. The difference (2 vs 0) is not
  statistically distinguishable (Fisher exact p about 0.47). 0/8 means "none of THESE attacks worked", not "injection is solved". Tools are read-only, which
  caps the damage of a successful injection to a wrong or manipulated answer.
- **Rate limits are per instance and reset on restart;** several instances multiply them. Behind a proxy the client address may be
  the proxy's, so the failed-auth throttle can lump users together. Needs a shared store / gateway in production.
- **No end-user identity:** a key identifies a caller, not a person; no key rotation tooling beyond replacing the hash; no key expiry.
- **Not done:** Secret Manager, service accounts, IAP/WAF, PII redaction, shipping the audit log, running the dependency audit in CI,
  TLS/size limits (assumed from the host), and a load test with an SLO report.
- **Revisit trigger:** multi-instance deployment (shared limiter), multiple end users (JWT), or a larger/adaptive attack set showing v1 failing.

## Amendment 2026-11-08 — independent code review (10 findings, all fixed)
A review of the gateway, agent, tools, MCP server and eval gate found problems in the work above. Fixed, each with a test:
- **`/ask` was not hardened.** Only the agent carried the injection rules; `/ask` still used the original prompt (which fell to
  2/8 attacks). It now uses the same security rules. Only the agent path was measured; `/ask` is covered by a test that the rules
  are present, not by an attack run.
- **A streaming run could leak its concurrency slot forever** (a semaphore released only inside a generator that may never start).
  Slots are now expiring leases, so a leak heals after the run's time budget plus 60 s.
- **"Busy" rejections burned quota** (daily cap and per-minute window were counted before the slot check). They are now refunded.
- **Internal and upstream error text reached clients** (database or Gemini error strings in the stream and in refusal answers). Clients
  now get generic messages; details go to the server log.
- **A non-`ToolError` failure inside a tool crashed the run.** It is now an observation the model can act on (retry, answer, or
  refuse), without leaking the cause.
- **The eval gate checked the candidate's settings but not the baseline's,** so a baseline built with a weaker retriever made the gate
  pass trivially. The baseline's settings are now checked too.
- **A negated term (`-china`) was inverted** by the BM25 keyword leg (the rewrite matched 4777 of 4867 chunks and scored the
  excluded word positively). Negated words are now dropped from the keyword query and the candidate query is built from lexemes
  directly. Side effect: hyphenated words are now counted correctly; the retrieval gate still passes (0 questions lost) and
  combined MRR moved 0.489 -> 0.491. That is a bug-fix side effect, not an adopted improvement.
- **`EA_ENVIRONMENT` was free text,** so `production` silently kept the API docs on. It is now `dev` or `prod`, anything else fails at startup.
- **Clients could set `max_steps` up to 12,** multiplying model calls per run inside the run cap. The step budget is now server-side
  (`EA_AGENT_MAX_STEPS`) and the default daily cap dropped from 200 to 50 runs to fit the free-tier quota.
- A stale module docstring (it still said there was no authentication) and a test that could never fail were corrected/removed.
The tests run in a clean environment without the optional embedding group (as CI does): 214 pass.

