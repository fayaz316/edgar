"""Stage 2: synthetic training questions (PROTOCOL.md, 'Training data'). Resumable; one API call per chunk.

  python -m evals.finetune.generate_questions [--limit N]

Reads evals/finetune/data/eligible.json, takes a stratified sample (water-filling across filings so JPMorgan's many chunks do
not swamp the 10-Qs of Apple and NVIDIA), and appends to evals/finetune/data/questions.jsonl. Stops cleanly on a daily quota error;
re-run to continue. Model and prompt are fixed here and committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(".env")
DATA = Path("evals/finetune/data")
MODEL = "gemini-3.1-flash-lite"
TARGET_CHUNKS = 1500
PAUSE_S = 4.2  # 15 requests/minute free tier
VERTEX_PAUSE_S = 0.3
REQUEST_TIMEOUT_MS = 60_000  # a hung call must fail and retry, not stall the run

PROMPT = """You write search questions for a search engine over SEC filings (10-K / 10-Q).
You get ONE passage from a filing. Write two questions that this passage answers:
- "direct": a natural question an analyst would type, answerable from the passage.
- "paraphrase": a different question about the same fact that does NOT reuse any four consecutive words from the passage.
Rules: each question must make sense without seeing the passage (never say "this passage" or "the above"); BOTH questions must
name the company from the filing line by its common name (NVIDIA, Apple, JPMorgan), never "the firm" or "the company" alone; keep
every date, period and number exact and add no fact that is not in the passage; no yes/no questions; under 220 characters.
If the passage has no standalone factual content (cover page, table of contents, signatures, a bare table), answer null for both.
Reply with JSON only: {"direct": "...", "paraphrase": "..."}

Filing: %(filing)s, section: %(section)s
Passage:
%(text)s
"""


def water_fill(sizes: dict[str, int], target: int) -> dict[str, int]:
    """Per-group quota: every group gets min(size, level), the level chosen so the total is <= target."""
    quota = {k: 0 for k in sizes}
    left = target
    open_groups = {k for k, v in sizes.items() if v > 0}
    while left > 0 and open_groups:
        share = max(left // len(open_groups), 1)
        for k in sorted(open_groups):
            take = min(share, sizes[k] - quota[k], left)
            quota[k] += take
            left -= take
        open_groups = {k for k in open_groups if quota[k] < sizes[k]}
    return quota


def sample_chunks(eligible: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    by_acc: dict[str, list[dict[str, Any]]] = {}
    for c in eligible:
        by_acc.setdefault(c["accession"], []).append(c)
    quota = water_fill({a: len(v) for a, v in by_acc.items()}, target)
    out: list[dict[str, Any]] = []
    for acc, rows in sorted(by_acc.items()):
        rows = sorted(rows, key=lambda c: hashlib.md5(f"{c['id']}ft-sample".encode()).hexdigest())
        out += rows[: quota[acc]]
    return sorted(out, key=lambda c: c["id"])


def words(s: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", s.lower()).split()


def shares_run(question: str, passage: str, n: int = 4) -> bool:
    q, p = words(question), words(passage)
    grams = {tuple(p[i : i + n]) for i in range(len(p) - n + 1)}
    return any(tuple(q[i : i + n]) in grams for i in range(len(q) - n + 1))


def parse_response(raw: str) -> dict[str, str | None] | None:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    out: dict[str, str | None] = {}
    for key in ("direct", "paraphrase"):
        v = obj.get(key)
        out[key] = v.strip() if isinstance(v, str) and 8 <= len(v.strip()) <= 300 else None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="stop after N new API calls (probe)")
    ap.add_argument(
        "--vertex",
        action="store_true",
        help="call the same model through Vertex AI (billed to GCP credits; needs GOOGLE_CLOUD_PROJECT and "
        "application-default credentials) instead of the free API key",
    )
    args = ap.parse_args()
    import psycopg
    from google import genai
    from google.genai import errors, types

    eligible = json.loads((DATA / "eligible.json").read_text())
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        names = {
            a: f"{t} {f}"
            for a, t, f in conn.execute("SELECT accession, ticker, form_type FROM documents")
        }
    chunks = sample_chunks(eligible, TARGET_CHUNKS)
    out_path = DATA / "questions.jsonl"
    done = (
        {json.loads(line)["chunk_id"] for line in out_path.read_text().splitlines()}
        if out_path.exists()
        else set()
    )
    todo = [c for c in chunks if c["id"] not in done]
    print(f"sample {len(chunks)} chunks; done {len(done)}; to do {len(todo)}")
    client = (
        genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location="global",
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
        )
        if args.vertex
        else genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS),
        )
    )
    cfg = types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json")
    calls = 0
    with out_path.open("a") as f:
        for c in todo:
            if args.limit is not None and calls >= args.limit:
                break
            prompt = PROMPT % {
                "filing": names[c["accession"]],
                "section": c["section"],
                "text": c["text"],
            }
            for attempt in range(4):
                try:
                    resp = client.models.generate_content(model=MODEL, contents=prompt, config=cfg)
                    break
                except errors.APIError as exc:
                    code = int(getattr(exc, "code", 0) or 0)
                    if code == 429 and "per day" in str(exc).lower():
                        print("daily quota reached; re-run tomorrow to continue")
                        return 0
                    if attempt == 3 or code not in (429, 500, 502, 503, 504):
                        print(f"stopping on API error {code}: {str(exc)[:200]}")
                        return 1
                    time.sleep(20.0 if code == 429 else 8.0 * (attempt + 1))
                except (
                    Exception
                ) as exc:  # network timeouts and resets are not APIError: retry them too
                    if attempt == 3:
                        print(f"stopping on network error: {type(exc).__name__}: {str(exc)[:200]}")
                        return 1
                    time.sleep(8.0 * (attempt + 1))
            calls += 1
            parsed = parse_response(resp.text or "")
            rec: dict[str, Any] = {"chunk_id": c["id"], "parsed": parsed is not None}
            if parsed:
                para = parsed.get("paraphrase")
                rec["direct"] = parsed.get("direct")
                rec["paraphrase"] = para if para and not shares_run(para, c["text"]) else None
                rec["paraphrase_echo_dropped"] = bool(para) and rec["paraphrase"] is None
            f.write(json.dumps(rec) + "\n")
            f.flush()
            time.sleep(VERTEX_PAUSE_S if args.vertex else PAUSE_S)
    print(f"made {calls} calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
