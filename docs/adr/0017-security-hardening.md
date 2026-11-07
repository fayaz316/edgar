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
