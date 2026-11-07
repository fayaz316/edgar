#!/usr/bin/env bash
# One-shot: stop the Gemini backfill, migrate the DB, embed everything with the free local
# model, and record the BEFORE retrieval baseline. Optional: continue through the parser-v2
# re-ingest and the AFTER measurement.
#
#   bash scripts/switch-to-local-embeddings.sh                 # steps 1-6 (baseline on old parser)
#   bash scripts/switch-to-local-embeddings.sh --through-reingest   # ...plus parser v2 + AFTER
#
# Everything is logged to data/logs/ (gitignored) so results can be reviewed without pasting.
set -euo pipefail
cd "$(dirname "$0")/.."

THROUGH_REINGEST=0
[[ "${1:-}" == "--through-reingest" ]] && THROUGH_REINGEST=1

mkdir -p data/logs evals/results
LOG="data/logs/switch-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

step() { printf '\n\033[1;36m== %s ==\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mSTOPPED: %s\033[0m\nlog: %s\n' "$*" "$LOG"; exit 1; }
trap 'die "a command failed (see the lines above)"' ERR

step "1/7 Docker running?"
docker info >/dev/null 2>&1 || die "Docker is not running. Run: open -a Docker  (wait for the whale icon to settle), then rerun."

step "2/7 Stop the old Gemini backfill (it writes vectors without a model tag)"
if pgrep -f "services.ingest.embed_backfill" >/dev/null; then
  pgrep -fl "services.ingest.embed_backfill" || true
  read -r -p "Stop it now? It is resumable, nothing is lost. [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || die "left the old backfill running; stop it (Ctrl-C in its terminal) and rerun."
  pkill -f "services.ingest.embed_backfill" || true
  sleep 2
else
  echo "no running backfill found"
fi

step "3/7 Database up + migration (tags existing vectors as gemini-embedding-001@768)"
make db-up
make db-migrate
make embed-status

step "4/7 Embed ALL chunks with the local model (first run: installs torch, downloads ~440 MB once)"
make embed EMBEDDER=local
make embed-status

step "5/7 BEFORE baseline: old-parser corpus + local model"
make eval-retrieval EMBEDDER=local
cp evals/results/latest.json evals/results/baseline-old-parser.json
echo "saved evals/results/baseline-old-parser.json"

if [[ "$THROUGH_REINGEST" -eq 0 ]]; then
  step "6/7 Done with the baseline. Next: rerun with --through-reingest"
  exit 0
fi

step "6/7 Re-ingest with parser v2 (cached HTML; unchanged text keeps its vector)"
docker compose up -d
make db-up
make reingest EMBEDDER=local
make embed EMBEDDER=local
make embed-status
make golden

step "7/7 AFTER: parser v2 + local model"
make eval-retrieval EMBEDDER=local
cp evals/results/latest.json evals/results/after-parser-v2.json
echo "saved evals/results/after-parser-v2.json"
printf '\n\033[1;32mALL DONE\033[0m  log: %s\n' "$LOG"
