"""Hash the frozen evaluation files so silent edits are caught.

python -m evals.freeze --check     # exit 1 if a frozen file differs from the manifest
python -m evals.freeze --update    # rewrite the manifest (a deliberate act; add a DECISION_LOG entry)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "baselines" / "manifest.json"
FROZEN = [
    "golden/golden_v0.yaml",
    "golden/golden_v1_heldout.yaml",
    "golden/golden_v2_heldout.yaml",
    "golden/golden_v3_heldout.yaml",
    "golden/HELDOUT_PROTOCOL.md",
    "claims/claims_v1.yaml",
    "claims/passages_v1.yaml",
    "claims/PROTOCOL.md",
    "claims/L1_DATES.md",
    "claims/UNCITED.md",
    "claims/INFERENCE.md",
    "claims/inference_questions.yaml",
    "claims/uncited_labeled.yaml",
    "claims/uncited_questions.yaml",
    "claims/claims_v2.yaml",
    "claims/passages_v2.yaml",
    "injection/PROTOCOL.md",
    "injection/attacks.py",
    "judge/PROTOCOL.md",
    "judge/questions.py",
    "judge/judge.py",
    "judge/calibration.py",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current() -> dict[str, str]:
    return {name: sha256_file(ROOT / name) for name in FROZEN}


def mismatches() -> list[str]:
    recorded: dict[str, str] = json.loads(MANIFEST.read_text())
    now = current()
    return [n for n in FROZEN if recorded.get(n) != now[n]]


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--update", action="store_true")
    args = ap.parse_args()
    if args.update:
        MANIFEST.parent.mkdir(exist_ok=True)
        MANIFEST.write_text(json.dumps(current(), indent=1, sort_keys=True) + "\n")
        print(
            f"updated {MANIFEST.relative_to(ROOT.parent)}; now add a DECISION_LOG entry saying why"
        )
        return 0
    bad = mismatches()
    if bad:
        print("frozen evaluation files changed:", *bad, sep="\n  ", file=sys.stderr)
        return 1
    print("frozen files match the manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
