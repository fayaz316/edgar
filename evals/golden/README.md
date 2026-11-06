# Golden set — schema v1

Every eval item is a YAML file (or row in `golden.tsv` once it outgrows files).
Schema is contract: the CI gate (Phase 3) refuses items that don't validate.

```yaml
id: nvda-10q-001
question: "What did NVIDIA say about data-center revenue concentration risk in its latest 10-Q?"
answer_type: grounded          # grounded | numeric | refusal | comparative
expected_evidence:             # passage anchors the answer MUST cite (>=1 for grounded)
  - accession: "0001045810-25-000023"
    section: "Risk Factors"
    snippet_hint: "concentration of revenue"
must_not_appear:               # hallucination tripwires
  - "specific percentage figures not present in the filing"
tags: [risk-factors, nvda, grounded-citation]
difficulty: medium
injected_attack: null          # or {type: prompt_injection, payload_ref: attacks/t001.txt}
```

Grading (Phase 3): faithfulness (LLM-as-judge, rubric-pinned), citation precision/recall
vs `expected_evidence`, refusal correctness, numeric exact-match, latency + €/query tracked per item.
Seeding rule: hand-write ≤50; the rest come from real usage logs of the deployed system.
