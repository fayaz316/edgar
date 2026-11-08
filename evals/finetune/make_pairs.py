"""Stage 3: turn generated questions into (query, positive, hard negative) triples (PROTOCOL.md).

  uv run --group local-embed python -m evals.finetune.make_pairs

Hard negatives come from the BASE model's ranking over ELIGIBLE chunks only (so no evaluation passage ever appears in training,
not even as a negative): a chunk at rank 10-40 that is not in the same document + section as the positive and is not a
near-duplicate of it. Writes data/pairs_train.jsonl, data/pairs_val.jsonl (gitignored) and pairs_manifest.json (committed).
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from evals.finetune.exclusion import NEAR_DUP_JACCARD, jaccard, shingles
from services.embeddings import BGE_QUERY_PREFIX, LOCAL_MODEL, LOCAL_REVISION

DATA = Path("evals/finetune/data")
MANIFEST = Path("evals/finetune/pairs_manifest.json")
MAX_PAIRS = 3000
RANK_LO, RANK_HI = 10, 40
VAL_FRACTION = 0.05
SEED = 42


def is_val_chunk(chunk_id: int) -> bool:
    return int(hashlib.md5(f"{chunk_id}ft-val".encode()).hexdigest(), 16) % 100 < VAL_FRACTION * 100


def pick_negative(
    ranked_ids: list[int],
    positive: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
    sh: dict[int, frozenset[tuple[str, ...]]],
    rng: random.Random,
) -> int | None:
    """Candidate = ranks RANK_LO..RANK_HI (1-based) among ranked_ids; drop same document+section and near-duplicates."""
    band = ranked_ids[RANK_LO - 1 : RANK_HI]
    ok = [
        i
        for i in band
        if i != positive["id"]
        and not (
            by_id[i]["document_id"] == positive["document_id"]
            and by_id[i]["section"] == positive["section"]
        )
        and jaccard(sh[i], sh[positive["id"]]) < NEAR_DUP_JACCARD
    ]
    return rng.choice(ok) if ok else None


def main() -> None:
    import numpy as np  # optional dependency (local-embed group); imported here so CI can import this module
    from sentence_transformers import SentenceTransformer

    eligible: list[dict[str, Any]] = json.loads((DATA / "eligible.json").read_text())
    by_id = {c["id"]: c for c in eligible}
    sh = {c["id"]: shingles(c["text"]) for c in eligible}
    model = SentenceTransformer(LOCAL_MODEL, revision=LOCAL_REVISION, trust_remote_code=False)
    ids = [c["id"] for c in eligible]
    doc_vecs = model.encode([c["text"] for c in eligible], batch_size=32, normalize_embeddings=True)

    queries: list[tuple[int, str, str]] = []  # chunk_id, kind, text
    for line in (DATA / "questions.jsonl").read_text().splitlines():
        r = json.loads(line)
        for kind in ("direct", "paraphrase"):
            if r.get(kind) and r["chunk_id"] in by_id:
                queries.append((r["chunk_id"], kind, r[kind]))
    qv = model.encode(
        [BGE_QUERY_PREFIX + q for _, _, q in queries], batch_size=32, normalize_embeddings=True
    )
    sims = qv @ doc_vecs.T
    rng = random.Random(SEED)
    triples: list[dict[str, Any]] = []
    dropped_no_negative = 0
    for row, (cid, kind, q) in enumerate(queries):
        order = np.argsort(-sims[row])
        ranked = [ids[j] for j in order]
        neg = pick_negative(ranked, by_id[cid], by_id, sh, rng)
        if neg is None:
            dropped_no_negative += 1
            continue
        triples.append(
            {
                "chunk_id": cid,
                "kind": kind,
                "query": q,
                "positive": by_id[cid]["text"],
                "negative_id": neg,
                "negative": by_id[neg]["text"],
                "positive_rank_base": ranked.index(cid) + 1,
            }
        )
    rng.shuffle(triples)
    triples = triples[:MAX_PAIRS]
    train = [t for t in triples if not is_val_chunk(t["chunk_id"])]
    val = [t for t in triples if is_val_chunk(t["chunk_id"])]
    for name, rows in (("pairs_train.jsonl", train), ("pairs_val.jsonl", val)):
        (DATA / name).write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    used = {t["chunk_id"] for t in triples} | {t["negative_id"] for t in triples}
    assert used <= set(ids), "pair uses a chunk outside the eligible set"
    ranks = [t["positive_rank_base"] for t in triples]
    manifest = {
        "pairs_train": len(train),
        "pairs_val": len(val),
        "dropped_no_negative": dropped_no_negative,
        "chunks_with_pairs": len({t["chunk_id"] for t in triples}),
        "base_model_positive_rank_median": int(np.median(ranks)) if ranks else None,
        "base_model_positive_in_top8": round(sum(r <= 8 for r in ranks) / len(ranks), 3)
        if ranks
        else None,
        "train_sha256": hashlib.sha256((DATA / "pairs_train.jsonl").read_bytes()).hexdigest(),
        "all_chunks_eligible_assertion": "passed",
        "negative_band_ranks": [RANK_LO, RANK_HI],
        "seed": SEED,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
