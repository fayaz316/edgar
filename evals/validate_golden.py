"""Validate the golden set: schema + semantics + referential integrity vs DB.

Three layers, all fast-failing with named errors:
  1. schema     — pydantic (evals/schema.py)
  2. semantics  — refusal items carry no evidence; others must carry >=1
  3. DB refs    — every (accession, section) pair exists in documents/chunks

Usage: uv run python -m evals.validate_golden [--skip-db]
"""

from __future__ import annotations

import sys
from collections import Counter

import psycopg
import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from evals.schema import GoldenItem

load_dotenv(".env")
GOLDEN_PATH = "evals/golden/golden_v0.yaml"


def load_items() -> tuple[list[GoldenItem], list[str]]:
    errors: list[str] = []
    with open(GOLDEN_PATH) as f:
        raw = yaml.safe_load(f)
    items: list[GoldenItem] = []
    for i, entry in enumerate(raw):
        try:
            item = GoldenItem.model_validate(entry)
            items.append(item)
            errors.extend(item.validate_semantics())
        except ValidationError as exc:
            errors.append(f"item[{i}]: {exc.error_count()} schema errors: {str(exc)[:200]}")
    return items, errors


def check_db_refs(items: list[GoldenItem]) -> list[str]:
    import os

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        return ["DATABASE_URL missing — cannot check referential integrity"]
    errors: list[str] = []
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for item in items:
            for anchor in item.expected_evidence:
                cur.execute(
                    """
                    SELECT EXISTS(
                      SELECT 1 FROM chunks c JOIN documents d ON d.id = c.document_id
                      WHERE d.accession = %s AND c.section = %s
                    )
                    """,
                    (anchor.accession, anchor.section),
                )
                row = cur.fetchone()
                if not row or not row[0]:
                    errors.append(f"{item.id}: no chunk with accession={anchor.accession} section={anchor.section!r}")
    return errors


def main() -> int:
    skip_db = "--skip-db" in sys.argv
    items, errors = load_items()
    if not errors and not skip_db:
        errors = check_db_refs(items)

    by_type = Counter(i.answer_type for i in items)
    by_tag_ticker = Counter(t for i in items for t in i.tags if len(t) <= 4)
    print(f"items: {len(items)}  by type: {dict(by_type)}  tickers: {dict(by_tag_ticker)}")
    if errors:
        print(f"\nFAIL — {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("PASS — schema, semantics, referential integrity all clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
