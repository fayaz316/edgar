# Edgar Analyst

A citation-grounded AI research analyst over SEC filings — built as a **one-person forward
deployment** for a simulated client (*Northwind Capital*, a 15-analyst fund): discovery →
scoped system → production rollout → eval gates → handover artifacts.

## Exit criteria per phase (no timelines — done = test passes)
| Phase | Done when |
|---|---|
| P0 guardrails | budget alerts live · apply/teardown clean · hello serving |
| P1 data+RAG | cited answers · hybrid search · ≥30 golden Qs |
| P2 agent+MCP | multi-tool trace · MCP callable from Claude Desktop |
| P3 evals | ≥100 Qs · CI blocks regressions |
| P4 hardening | auth · injection corpus · cache ≥30% · SLOs under k6 |
| P5 finetune | ≥500-example dataset · LoRA on Mac · vLLM/GKE evenings |
| P6 UI+demo | citations+trace UI · 5-min video |
| P7 wrapper | ADRs, runbook, security review, postmortem, blog |

## Dev

```bash
uv sync
uv run pytest                      # tests
uv run ruff check . && uv run mypy
make help                          # all targets, incl. infra lifecycle (bootstrap/plan/apply/teardown)

# data + evals loop
make db-up && make db-migrate     # local pgvector (+ one-time migration: vectors tagged by model)
make embed                         # embed with the local HF model (free; EMBEDDER=gemini for the API)
make fetch                         # cache raw filing HTML (SEC only, no DB)
make reingest                      # re-parse cached HTML -> Postgres, reusing unchanged embeddings
make golden                        # validate golden set vs the live corpus
make eval-retrieval                # retrieval recall (hit@k, MRR) — run before/after any parser change
```

Cost stance: scale-to-zero everywhere, `make teardown` is the panic button. Budget alarms at €5/€25/€100.
