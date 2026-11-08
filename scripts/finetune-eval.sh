#!/usr/bin/env bash
# Score the fine-tuned embedder against the control and apply the pre-registered rule (evals/finetune/PROTOCOL.md).
#   bash scripts/finetune-eval.sh            # needs: Postgres up, scratch DB `edgar_ft` embedded with the candidate,
#                                            #        EA_FT_MODEL_PATH set to the checkpoint directory
# Control runs on the main database with the local base model; candidate runs on the scratch database. Product defaults only.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${EA_FT_MODEL_PATH:?set EA_FT_MODEL_PATH to the checkpoint directory}"
MAIN_URL="$DATABASE_URL"; FT_URL="${DATABASE_URL%/edgar}/edgar_ft"
C=data/logs/ft_control; K=data/logs/ft_candidate
rm -rf "$C" "$K"; mkdir -p "$C" "$K"
uv run python -m evals.freeze --check
declare -a SETS=("golden_v0:golden_v0.yaml" "heldout_v1:golden_v1_heldout.yaml" "heldout_v2:golden_v2_heldout.yaml" "heldout_v3:golden_v3_heldout.yaml" "heldout_v4:golden_v4_heldout.yaml")
for s in "${SETS[@]}"; do
  name="${s%%:*}"; file="evals/golden/${s##*:}"
  echo "control   $name"; DATABASE_URL="$MAIN_URL" uv run --group local-embed python -m evals.run_retrieval --embedder local --golden "$file" --out "$C/$name.json" >"$C/$name.log" 2>&1
  echo "candidate $name"; DATABASE_URL="$FT_URL" uv run --group local-embed python -m evals.run_retrieval --embedder finetuned --golden "$file" --out "$K/$name.json" >"$K/$name.log" 2>&1
done
uv run python -m evals.finetune.decide --control "$C" --candidate "$K" --out evals/finetune/decision.json
