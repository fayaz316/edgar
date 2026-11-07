# Architecture Decision Records (ADRs)

An ADR is a **one-page record of one decision**: what we were facing, what we chose, what
else we could have chosen, and what the choice costs us. The format is Michael Nygard's
(2011): *Context → Decision → Consequences*, plus a *Status*.

## Why bother?
Code shows **what** the system does. It cannot show **why** — which options were rejected,
what constraint forced the choice, what we knowingly gave up. Six months later (or in an
interview, or in a customer's review meeting) "why is it built like this?" is the question
that gets asked, and nobody remembers. For a forward-deployed engineer this is the job:
you leave behind a system someone else must run, and the ADRs are how they inherit your
reasoning, not just your code.

## When to write one
Write an ADR when the decision is **hard to reverse**, has **real alternatives**, or would
**surprise a newcomer**. (Database choice, retrieval design, how failures are handled.)
Skip it for choices that are cheap to change or that have only one sensible answer.

## Development log vs ADR
| a chronological development log | `docs/adr/` |
|---|---|
| chronological story, lessons, dead ends | one decision per file, stable reference |
| "what happened" | "what we decided and why" |
| rewritten freely | **immutable once accepted** |

## Rules
1. **One decision per ADR**, ~1 page. If it needs more, it is two decisions.
2. **Record the alternatives and why they lost.** An ADR with no rejected options is just an announcement.
3. **List the bad consequences too.** Honest costs are what make an ADR trustworthy.
4. **Never rewrite history.** If you change your mind, write a new ADR that *supersedes* the old one, and edit only the old one's `Status` line to point at it.
5. Number sequentially; never reuse a number. Retroactive ADRs are fine — say so in the Status.
6. Make the decision **testable** where you can: name the metric or trigger that would make you revisit it.

## Template
```markdown
# ADR NNNN — <short decision title>
Status: Proposed | Accepted | Superseded by ADR XXXX · Date: YYYY-MM-DD

## Context        (the forces: requirements, constraints, what we knew then)
## Options considered   (each with the one-line reason it won or lost)
## Decision       ("We will …" — active voice, specific)
## Consequences   (good, bad, and what to watch; the revisit trigger)
```

## Index
| # | Decision | Status |
|---|---|---|
| 0001 | Serverless-first on GCP; K8s only as a proven evening | Accepted (decision #2 superseded by 0002) |
| 0002 | Local-first Postgres (Docker pgvector) → Cloud SQL for the demo | Accepted |
| 0003 | Hybrid retrieval: Postgres FTS + pgvector fused with RRF | Accepted (retroactive) |
| 0004 | Cite-or-refuse: unverifiable answers are suppressed | Accepted (retroactive) |
| 0005 | Section-aware chunking of 10-K/10-Q | Accepted — under revision (retroactive) |
| 0006 | Switchable embedder; local Hugging Face model as default | Accepted |
