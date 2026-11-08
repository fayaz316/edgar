# Edgar Analyst

A citation-grounded AI research analyst over SEC filings (10-K / 10-Q for Apple, JPMorgan and NVIDIA), built as a
**one-person forward deployment** for a simulated client: discovery → scoped system → evals → hardening → handover artifacts.

**What it does:** answers questions with passage-level citations, refuses when the filings do not contain the answer, and can
run a multi-step agent whose every tool call and verification step is visible in a UI. Retrieval and agent changes are judged
by pre-registered experiments and a regression gate, not by feel (see *How decisions are made*).

## Status (honest)
| Phase | State |
|---|---|
| P0 guardrails | Terraform, budget alerts, hello service. Done earlier. |
| P1 data + RAG | **Done**, with one deliberate gap: a cross-encoder reranker is built but not enabled (it lost recall; ADR 0011). |
| P2 agent + MCP | Tool registry, MCP server, LangGraph agent, streaming API, trace UI: **done and tested**. Missing: the contradiction-hunter sub-agent; Claude Desktop is not connected yet. |
| P3 evals | 4 retrieval sets (78 questions), two claim sets (36 + 20 labeled claims), a two-layer regression gate, and a calibrated independent faithfulness judge with a first measurement (ADR 0018). Missing: ≥100 questions, the full gate in CI, an answer-quality gate, a human check of the judge. |
| P4 hardening | API-key auth, rate limits, strict CSP, prompt-injection defence, threat model, clean dependency audit. Missing: Secret Manager/service accounts/IAP, shared rate-limit store, semantic cache, load test with SLOs. |
| P5 fine-tuning | Not started. |
| P6 UI + demo | A single-file UI exists; the Next.js app and the demo video do not. |
| P7 wrapper | 21 ADRs and a threat model exist; runbook, postmortem and blog post do not. |

Decisions and their evidence: `docs/adr/`.

## Quick start
```bash
uv sync --group local-embed                      # local embedding model (free); gemini is optional
make db-up && make db-migrate                    # local pgvector
make fetch && make reingest && make embed        # build the corpus (SEC data, then local bge embeddings)

uv run python -m services.gateway.keys me        # prints an API key ONCE + the line for EA_API_KEYS
export EA_API_KEYS="me:<the hash it printed>"    # or, for local use only: EA_AUTH=off
uv run --group local-embed uvicorn services.gateway.main:app --port 8089
# open http://localhost:8089/  -> paste your key, ask a question, watch the trace

uv run --group local-embed python -m services.agent.run "How do NVIDIA's and Apple's supply-chain risks differ?"
make mcp                                          # MCP server over stdio (config snippet: docs/adr/0012-*.md)
```
Needs `DATABASE_URL` and `GEMINI_API_KEY` in `.env` (see `.env.example`). Generation uses Gemini; embeddings are local.

## Configuration (environment variables, `EA_` prefix)
| Variable | Default | Meaning |
|---|---|---|
| `EA_ENVIRONMENT` | `dev` | `dev` or `prod`; anything else fails at startup. `prod` disables the API docs and refuses `EA_AUTH=off`. |
| `EA_API_KEYS` | (none) | `name:sha256hex,...` from `python -m services.gateway.keys`. Required unless `EA_AUTH=off` (dev only). |
| `EA_AUTH` | `on` | `off` only works when `EA_ENVIRONMENT=dev`. |
| `EA_RATE_PER_MIN` | 20 | Calls per key per minute on spending endpoints. |
| `EA_AGENT_DAILY_CAP` | 50 | Agent runs per key per UTC day (each is several model calls; tune to your Gemini quota). |
| `EA_AGENT_MAX_STEPS` | 8 | Model turns per run; clients cannot raise it. |
| `EA_AGENT_MAX_SECONDS` | 120 | Wall-clock budget per run, checked between steps. |
| `EA_EMBEDDER` | `local` | Must match the model the corpus was embedded with. |

## Quality gates
```bash
make verify          # lint + strict types + tests + the full retrieval gate (needs the corpus and local model)
make eval-gate       # retrieval regression gate vs the committed baseline (evals/GATE.md)
make eval-gate-baseline   # regenerate the baseline: deliberate; add a DECISION_LOG entry
```
CI (`.github/workflows/ci.yml`) runs lint, strict mypy, the tests, golden-set validation, the frozen-file check and an image build.
It does **not** run the retrieval gate: runners have no corpus or embedding model (ADR 0016).

## How decisions are made
Retrieval and safety changes follow one pattern: write the rule and the success threshold first, run each variant once on data
the change was not designed against, apply the rule by script, record the outcome whichever way it falls
(`evals/golden/HELDOUT_PROTOCOL.md`, `evals/claims/PROTOCOL.md`, `evals/injection/PROTOCOL.md`, `evals/GATE.md`).
Several "obvious" improvements were rejected this way (an OR keyword leg, a reranker). Each evaluation set is logged with how
often it has informed a decision (`evals/golden/DECISION_LOG.md`), and frozen files are hash-checked.

## Map
| Path | What |
|---|---|
| `services/ingest/` | fetch, parse (form-aware sections, tables kept), embed |
| `services/gateway/` | FastAPI: `/ask`, `/agent`, `/agent/stream`, UI, security, BM25 + vector hybrid retrieval |
| `services/agent/` | LangGraph plan/act/verify loop, Gemini adapter, claim-level grounding check |
| `services/tools/`, `services/mcp/` | one tool registry, exposed over MCP |
| `evals/` | golden sets, claims set, injection set, runners, regression gate, frozen-file manifest |
| `docs/adr/`, `docs/security/` | 21 decision records, the threat model |
| `infra/` | Terraform (state in GCS) |

## Known limits
- 78 retrieval questions and 36 claims: small, so only large effects are visible; sets written by the author.
- The claim check catches changed figures, wrong dates and wrong-company claims, not invented causes or flipped direction (ADR 0014, ADR 0019).
- Prompt-injection defence: 0/8 attacks succeeded on a small hand-written set against the agent; `/ask` carries the same rules but
  was not separately measured (ADR 0017).
- Every claim sentence must now carry a citation (ADR 0020), but a citation only makes a claim checkable, not true: comparison sentences can carry citations their passages do not support. An "Inference:" label (prompt v2) was tried and not adopted (ADR 0021), so this risk is open.
- Rate limits live in process memory (per instance). No end-user identity beyond API keys.
- The container image has no torch, so the local embedder cannot run in it; a deployed service needs torch in the image or a Gemini re-embed.
- Nothing is deployed to GCP beyond the Phase 0 canary; deploying creates billable resources and needs an explicit go-ahead.

Cost stance: scale-to-zero everywhere, `make teardown` is the panic button. Budget alarms at €5/€25/€100.
