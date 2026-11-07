# Threat model — Edgar Analyst gateway (written before the hardening work; updated as controls land)

Scope: the HTTP gateway (`/ask`, `/agent`, `/agent/stream`, the UI at `/`), the agent and its tools, the database, the
Gemini key. Out of scope: the SEC and Google as providers, the developer's laptop.

## What matters (assets)
| Asset | Why it matters |
|---|---|
| Gemini API key and quota | Direct money/quota loss if anyone can call `/agent` anonymously. |
| Answer integrity | The product's promise is "cite or refuse". A wrong or manipulated answer is the failure that matters most. |
| Availability | One agent run takes several model calls; a few concurrent requests can exhaust the free tier. |
| Corpus integrity | Poisoned passages produce poisoned answers. (Public SEC text: confidentiality is low.) |
| API keys, logs | Leaked keys give free use; logs can leak keys or user questions. |

## Who might attack (actors)
Anonymous internet user · authenticated but abusive user · text inside retrieved documents (indirect prompt injection)
· a compromised dependency · a leaked key.

## Threats and controls
| # | Threat | Control | Status |
|---|---|---|---|
| T1 | Anonymous use spends the Gemini key | API-key authentication on every spending endpoint; fail closed in production | built |
| T2 | One key (or script) floods the service | Per-key rate limit and daily agent-run cap; global concurrency cap of 2 | built (in memory, per instance) |
| T3 | Key theft / leakage | Keys are 256-bit random, shown once, only their SHA-256 stored in config; constant-time comparison; never logged (tested); UI keeps the key in `sessionStorage` only | built |
| T4 | Guessing keys | 256-bit keys make guessing infeasible; failed attempts are throttled per client IP and audit-logged | built |
| T5 | XSS through model or filing text | Untrusted text only via `textContent`; strict CSP (`script-src 'self'`, no inline script), `nosniff`, `frame-ancestors 'none'` | built |
| T6 | Indirect prompt injection in a retrieved passage | Hardened prompt (security rules + an "untrusted data" note on every tool result); tools are read-only (no write, exec or network), so the blast radius is a wrong answer; answers still pass the grounding check | built + measured: 2/8 attacks succeeded against the original prompt, 0/8 against the hardened one (ADR 0017; small set) |
| T7 | Runaway agent (loops, slow model) | Limits on model turns, tool calls, repairs; wall-clock deadline; question length cap | built |
| T8 | SQL injection | All SQL uses bound parameters (the ticker, form type and section filters included); a test asserts user text never reaches the SQL string | built |
| T9 | Secrets in the repo or logs | `.env` ignored; log redaction test; secret scan in the review checklist | partly |
| T10 | Vulnerable or malicious dependency | `uv.lock` pins versions with hashes; `pip-audit` on the locked runtime dependencies found no known vulnerabilities (2026-11-08) | audited once; not in CI |
| T11 | CSRF | Auth is a bearer header, not a cookie, so browsers do not attach it automatically | by design |
| T12 | Corpus poisoning | Ingest only from SEC EDGAR; every chunk keeps its accession for traceability | partial: no integrity check after ingest |

## Not done (residual risk, stated plainly)
- **No end-user identity or JWT.** API keys identify callers, not people. Sessions/JWT are a later step.
- **Rate limits live in process memory:** they apply per instance, reset on restart, and are bypassed by running several
  instances. A shared store (Redis) or an API gateway is needed in production.
- **No Secret Manager, least-privilege service accounts, IAP or WAF:** these are infrastructure changes that need a
  Terraform apply (and cost approval); not applied.
- **Prompt injection is mitigated, not solved.** The measured attack success rate is in ADR 0017; it is not zero-proof.
- **No PII redaction pass** on user questions; questions are not written to logs (only length and a short hash), which
  limits the exposure but is not redaction.
- **TLS and request-size limits** are assumed to come from the hosting layer (Cloud Run); not verified here.
