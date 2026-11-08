"""Stage 1 of the fine-tune data build: which chunks may be used for training (PROTOCOL.md, 'Training data').

Writes evals/finetune/data/eligible.json (gitignored: chunk text) and evals/finetune/eligible_manifest.json (committed:
counts, hashes, the assertion result). Stops with an error if any eligible chunk is in the exclusion set.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from evals.finetune.exclusion import Chunk, exclusion_set
from evals.finetune.sample_v4 import existing_anchors_and_skips, load_chunks

load_dotenv(".env")
DATA = Path("evals/finetune/data")
MANIFEST = Path("evals/finetune/eligible_manifest.json")
MIN_CHARS, MAX_CHARS, MIN_WORDS, MAX_DIGIT_FRACTION = 300, 2000, 40, 0.30


def digit_fraction(text: str) -> float:
    return sum(ch.isdigit() for ch in text) / max(len(text), 1)


def is_eligible(c: Chunk) -> bool:
    return (
        MIN_CHARS <= len(c.text) <= MAX_CHARS
        and len(c.text.split()) >= MIN_WORDS
        and digit_fraction(c.text) <= MAX_DIGIT_FRACTION
    )


def main() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        chunks = load_chunks(conn)
    anchors, skips = (
        existing_anchors_and_skips()
    )  # globs golden_*.yaml: includes v4 and its skipped ids
    excluded = exclusion_set(chunks, anchors, skips)
    eligible = [c for c in chunks if c.id not in excluded and is_eligible(c)]
    assert not ({c.id for c in eligible} & excluded), "leak: eligible chunk is in the exclusion set"
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "eligible.json").write_text(
        json.dumps(
            [
                {
                    "id": c.id,
                    "document_id": c.document_id,
                    "accession": c.accession,
                    "section": c.section,
                    "seq": c.seq,
                    "text": c.text,
                }
                for c in eligible
            ]
        )
    )
    by_acc: dict[str, int] = {}
    for c in eligible:
        by_acc[c.accession] = by_acc.get(c.accession, 0) + 1
    manifest = {
        "chunks_total": len(chunks),
        "evidence_anchors": len(anchors),
        "skipped_ids_in_headers": len(skips),
        "excluded": len(excluded),
        "eligible": len(eligible),
        "eligible_by_accession": dict(sorted(by_acc.items())),
        "excluded_ids_sha256": hashlib.sha256(
            ",".join(map(str, sorted(excluded))).encode()
        ).hexdigest(),
        "eligible_ids_sha256": hashlib.sha256(
            ",".join(str(c.id) for c in eligible).encode()
        ).hexdigest(),
        "leak_assertion": "passed",
        "rules": {
            "chars": [MIN_CHARS, MAX_CHARS],
            "min_words": MIN_WORDS,
            "max_digit_fraction": MAX_DIGIT_FRACTION,
        },
    }
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
