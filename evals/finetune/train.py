"""Stage 4: the single fine-tuning run (hyperparameters fixed in PROTOCOL.md; do not tune).

  python -m evals.finetune.train --pairs evals/finetune/data/pairs_train.jsonl --val evals/finetune/data/pairs_val.jsonl --out DIR

Runs on a plain pip install (sentence-transformers, datasets, accelerate), so it works on a cloud VM without the repo's other
dependencies. Writes the weights, model_id.txt (tag from the weights' SHA-256) and training_log.json (loss history).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

BASE = "BAAI/bge-base-en-v1.5"
BASE_REVISION = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"  # same pin as services/embeddings.py
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
LR, BATCH, EPOCHS, WARMUP, MAX_LEN, SEED = 1e-5, 32, 1, 0.1, 512, 42


def read(path: str) -> list[dict[str, str]]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def main() -> None:
    import torch
    from datasets import Dataset
    from sentence_transformers import (
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
    )
    from sentence_transformers.losses import MultipleNegativesRankingLoss
    from sentence_transformers.training_args import BatchSamplers

    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--max-steps", type=int, default=-1, help="dry-run only; the real run leaves this at -1"
    )
    args = ap.parse_args()

    model = SentenceTransformer(BASE, revision=BASE_REVISION, trust_remote_code=False)
    model.max_seq_length = MAX_LEN

    def ds(rows: list[dict[str, str]]) -> Dataset:
        return Dataset.from_dict(
            {
                "anchor": [QUERY_PREFIX + r["query"] for r in rows],
                "positive": [r["positive"] for r in rows],
                "negative": [r["negative"] for r in rows],
            }
        )

    train, val = ds(read(args.pairs)), ds(read(args.val))
    cuda = torch.cuda.is_available()
    targs = SentenceTransformerTrainingArguments(
        output_dir=str(Path(args.out) / "checkpoints"),
        num_train_epochs=EPOCHS,
        max_steps=args.max_steps,
        per_device_train_batch_size=BATCH,
        per_device_eval_batch_size=BATCH,
        learning_rate=LR,
        warmup_ratio=WARMUP,
        fp16=cuda,
        seed=SEED,
        batch_sampler=BatchSamplers.NO_DUPLICATES,  # two questions on one chunk must not be in-batch negatives of each other
        eval_strategy="no",
        save_strategy="no",
        logging_steps=5,
        report_to="none",
    )
    trainer = SentenceTransformerTrainer(
        model=model, args=targs, train_dataset=train, loss=MultipleNegativesRankingLoss(model)
    )
    trainer.train()
    val_loss = trainer.evaluate(eval_dataset=val)  # sanity only: never used to pick a checkpoint

    out = Path(args.out)
    model.save_pretrained(str(out / "model"))
    weights = next((out / "model").glob("*.safetensors"))
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    (out / "model" / "model_id.txt").write_text(f"edgar-ft-bge-base@{digest[:8]}\n")
    (out / "training_log.json").write_text(
        json.dumps(
            {
                "base": BASE,
                "revision": BASE_REVISION,
                "hyperparameters": {
                    "lr": LR,
                    "batch": BATCH,
                    "epochs": EPOCHS,
                    "warmup": WARMUP,
                    "max_len": MAX_LEN,
                    "seed": SEED,
                },
                "train_pairs": len(train),
                "val_pairs": len(val),
                "cuda": cuda,
                "weights_sha256": digest,
                "val_metrics": val_loss,
                "log_history": trainer.state.log_history,
            },
            indent=1,
        )
    )
    print(f"saved {out / 'model'} as edgar-ft-bge-base@{digest[:8]}")


if __name__ == "__main__":
    main()
