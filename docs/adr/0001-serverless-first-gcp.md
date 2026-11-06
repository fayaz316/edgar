# ADR 0001 — Serverless-first on GCP; Kubernetes only as a proven evening

Status: Accepted · Context: a small fixed cloud-credit budget, one operator.

## Context
The system must run for near-€0 while idle, survive a solo dev's irregular cadence, and still
exercise Kubernetes and GPU inference where they are genuinely needed.

## Decision
1. All services run on **Cloud Run, min-instances=0** — free tier covers our traffic class.
2. Postgres: **Supabase free (dev)** → smallest **Cloud SQL (final/demo phase only)**.
3. GPU/K8s exposure happens twice, inside scripted envelopes (`gpu-up`/`gpu-down`,
   Cloud Scheduler-enforced teardown): one **spot-L4 vLLM** benchmark session, one
   **GKE Autopilot** deployment session. No long-lived clusters, ever.

## Consequences
- Cold starts on first request after idle (acceptable: research workflows aren't ms-critical).
- Stateful deps (pg) are external from day one — good discipline anyway.
- K8s manifests live in `infra/k8s/` and are CI-validated (kubeconform) even though they
  rarely run — the manifests are an artifact, not just infra.
- If a "customer" demo needs always-on, the cost report documents the step-up honestly.
