"""Sample v4 candidate chunks per PROTOCOL.md (seed 'heldout-v4'; excludes v0-v3 evidence + their skipped ids)."""

from __future__ import annotations

import glob
import os

import psycopg
import yaml
from dotenv import load_dotenv

from evals.finetune.exclusion import Chunk, evidence_chunk_ids, skipped_ids_from_header
from evals.schema import EvidenceAnchor

load_dotenv(".env")
PER_GROUP = 6


def load_chunks(conn: psycopg.Connection) -> list[Chunk]:
    rows = conn.execute(
        "SELECT c.id, c.document_id, d.accession, c.section, c.seq, c.text FROM chunks c "
        "JOIN documents d ON d.id = c.document_id ORDER BY c.id"
    ).fetchall()
    return [Chunk(*r) for r in rows]


def existing_anchors_and_skips() -> tuple[list[EvidenceAnchor], set[int]]:
    anchors: list[EvidenceAnchor] = []
    skips: set[int] = set()
    for f in sorted(glob.glob("evals/golden/golden_*.yaml")):
        text = open(f).read()
        skips |= skipped_ids_from_header(text)
        for it in yaml.safe_load(text):
            anchors += [EvidenceAnchor(**e) for e in it.get("expected_evidence") or []]
    return anchors, skips


def main() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        chunks = load_chunks(conn)
        anchors, skips = existing_anchors_and_skips()
        used = evidence_chunk_ids(chunks, anchors) | skips
        rows = conn.execute(
            """
            SELECT id, ticker, form_type, section, len, filed FROM (
              SELECT c.id, d.ticker, d.form_type, c.section, length(c.text) AS len, d.filed_at::date AS filed,
                     row_number() OVER (PARTITION BY d.ticker, d.form_type
                                        ORDER BY md5(c.id::text || 'heldout-v4')) AS rn
              FROM chunks c JOIN documents d ON d.id = c.document_id
              WHERE length(c.text) BETWEEN 500 AND 1500 AND c.id <> ALL(%s)
            ) t WHERE rn <= %s ORDER BY ticker, form_type, rn
            """,
            (list(used), PER_GROUP),
        ).fetchall()
    print(f"excluded from sampling: {len(used)} chunks; sampled {len(rows)}")
    for r in rows:
        print(*r, sep="\t")


if __name__ == "__main__":
    main()
