#!/usr/bin/env bash
# Full retrieval gate (evals/GATE.md, layer 2): run the product-default retriever over all four question
# sets and compare with the committed baseline. Needs Postgres with the corpus and the local embedder.
#
#   bash scripts/eval-gate.sh              # compare with evals/baselines/retrieval_baseline.json
#   bash scripts/eval-gate.sh --baseline   # regenerate the baseline (deliberate; add a DECISION_LOG entry)
#
# exit 0 = pass, 1 = regression, 2 = could not run / not comparable
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=data/logs/gate
BASELINE=evals/baselines/retrieval_baseline.json
rm -rf "$OUT"; mkdir -p "$OUT"

uv run python -m evals.freeze --check || { echo "frozen evaluation files were edited; see evals/GATE.md"; exit 2; }
docker info >/dev/null 2>&1 || { echo "Docker is not running"; exit 2; }

run() {  # name golden-file ; NO flags other than the golden file: the gate tests the product defaults
  echo "running $1 ..."
  uv run --group local-embed python -m evals.run_retrieval --embedder local --golden "$2" --out "$OUT/$1.json" \
    >"$OUT/$1.log" 2>&1 || { echo "eval failed for $1; see $OUT/$1.log"; tail -5 "$OUT/$1.log"; exit 2; }
}
run golden_v0   evals/golden/golden_v0.yaml
run heldout_v1  evals/golden/golden_v1_heldout.yaml
run heldout_v2  evals/golden/golden_v2_heldout.yaml
run heldout_v3  evals/golden/golden_v3_heldout.yaml

uv run python -m evals.gate build --results-dir "$OUT" --out "$OUT/candidate.json"
if [[ "${1:-}" == "--baseline" ]]; then
  cp "$OUT/candidate.json" "$BASELINE"
  echo "baseline written to $BASELINE: commit it with a DECISION_LOG entry explaining why"
  exit 0
fi
uv run python -m evals.gate compare --baseline "$BASELINE" --candidate "$OUT/candidate.json"
