"""Embedding providers behind one small interface.

Why an interface: the embedding model is the most likely thing to change (quota walls,
cost, data-residency, quality). Callers (backfill, retriever, evals) depend on `Embedder`,
never on a vendor SDK, so swapping providers is a setting, not a rewrite.

Two rules that keep vectors honest:
  * every stored vector is tagged with `model_id`; vectors from different models are NOT
    comparable, so retrieval filters on the tag and the backfill re-embeds anything whose
    tag differs from the active model.
  * both providers emit 768 dimensions, matching the `vector(768)` column.

Providers:
  gemini - Google `gemini-embedding-001` (API; free tier is quota-limited, ~24 chunks/min
           in practice).
  local  - BAAI `bge-base-en-v1.5` via sentence-transformers (Hugging Face's own library),
           run on this machine: no quota, no network after the first download, no data
           leaves the box. Weights pinned by git revision, safetensors, never
           trust_remote_code. Needs the optional dependency group:  uv sync --group local-embed
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Protocol

DIMS = 768

GEMINI_MODEL = "gemini-embedding-001"
GEMINI_MODEL_ID = f"{GEMINI_MODEL}@{DIMS}"

LOCAL_MODEL = "BAAI/bge-base-en-v1.5"
# Pinned commit of the model repo (supply-chain: we load exactly these bytes, not "main").
LOCAL_REVISION = "a5beb1e3e68b9ab74eb54cfd186867f64f240e1a"
LOCAL_MODEL_ID = f"{LOCAL_MODEL}@{LOCAL_REVISION[:8]}"
# From the model card: queries get this instruction, passages get none.
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# "finetuned": a locally trained checkpoint (evals/finetune/PROTOCOL.md). Its tag is read from <dir>/model_id.txt, where
# EA_FT_MODEL_PATH names <dir>, so a corpus embedded by it can never be mistaken for one embedded by another model.
FT_PLACEHOLDER = "edgar-ft-bge-base@unset"
MODEL_IDS: dict[str, str] = {
    "gemini": GEMINI_MODEL_ID,
    "local": LOCAL_MODEL_ID,
    "finetuned": FT_PLACEHOLDER,
}


def ft_model_dir() -> Path:
    raw = os.environ.get("EA_FT_MODEL_PATH", "").strip()
    if not raw:
        raise ValueError("EA_FT_MODEL_PATH must name the fine-tuned checkpoint directory")
    return Path(raw)


def ft_model_id() -> str:
    tag = (ft_model_dir() / "model_id.txt").read_text().strip()
    if not tag.startswith("edgar-ft-"):
        raise ValueError(f"unexpected fine-tuned model tag {tag!r}")
    return tag


class EmbeddingError(RuntimeError):
    """Embedding failed (quota, network, bad response). Distinct from DB errors so the API
    can answer 502 (upstream) rather than 500 (our bug)."""


class Embedder(Protocol):
    model_id: str  # stored with every vector
    dims: int
    batch_size: int  # preferred backfill batch
    pause_s: float  # politeness pause between backfill batches (quota pacing)

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def model_id_for(name: str) -> str:
    """Model tag for a provider name WITHOUT loading it (ingest only needs the tag)."""
    if name == "finetuned":
        return ft_model_id()
    try:
        return MODEL_IDS[name]
    except KeyError:
        raise ValueError(f"unknown embedder {name!r}; choose from {sorted(MODEL_IDS)}") from None


# --------------------------------------------------------------------------- Gemini
GEMINI_MAX_ATTEMPTS = 3
QUOTA_WAIT_S = 65.0  # per-minute windows: any shorter wait is a wasted retry


class GeminiEmbedder:
    model_id = GEMINI_MODEL_ID
    dims = DIMS
    batch_size = 50
    pause_s = 62.0

    def __init__(self, api_key: str, client: Any | None = None) -> None:
        if client is None:
            from google import genai  # lazy: local-only runs never need it

            client = genai.Client(api_key=api_key)
        self._client = client

    def _embed(self, contents: str | list[str], task_type: str) -> list[list[float]]:
        from google.genai import types

        resp = self._client.models.embed_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=DIMS),
        )
        want = 1 if isinstance(contents, str) else len(contents)
        if resp.embeddings is None or len(resp.embeddings) != want:
            raise EmbeddingError(
                f"embedding count mismatch: {len(resp.embeddings or [])} vs {want}"
            )
        out: list[list[float]] = []
        for e in resp.embeddings:
            if e.values is None:
                raise EmbeddingError("embedding vector is None")
            out.append(list(e.values))
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        last: Exception | None = None
        for attempt in range(GEMINI_MAX_ATTEMPTS):
            try:
                return self._embed(texts, "RETRIEVAL_DOCUMENT")
            except Exception as exc:  # SDK raises many types; classify by message
                last = exc
                msg = str(exc)
                quota = "429" in msg or "RESOURCE_EXHAUSTED" in msg
                time.sleep(QUOTA_WAIT_S if quota else min(2.0**attempt * 2, 60))
        raise EmbeddingError(
            f"gemini embedding failed after {GEMINI_MAX_ATTEMPTS} attempts: {str(last)[:200]}"
        )

    def embed_query(self, text: str) -> list[float]:
        try:
            return self._embed(text, "RETRIEVAL_QUERY")[0]
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"query embedding failed: {str(exc)[:150]}") from exc


# --------------------------------------------------------------------------- local (HF)
class LocalEmbedder:
    model_id = LOCAL_MODEL_ID
    dims = DIMS
    batch_size = 32
    pause_s = 0.0

    def __init__(self, model: Any | None = None, device: str | None = None) -> None:
        self._model = model
        self._device = device

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    "local embedder needs the optional group: uv sync --group local-embed"
                ) from exc
            self._model = SentenceTransformer(
                LOCAL_MODEL,
                revision=LOCAL_REVISION,
                device=self._device,
                trust_remote_code=False,  # never execute code shipped with a model repo
            )
            got = self._model.get_sentence_embedding_dimension()
            if got != DIMS:
                raise EmbeddingError(f"{LOCAL_MODEL} produced {got} dims, schema expects {DIMS}")
        return self._model

    def _encode(self, texts: list[str]) -> list[list[float]]:
        try:
            vecs = self._load().encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,  # unit vectors -> cosine == dot product
                show_progress_bar=False,
            )
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"local embedding failed: {str(exc)[:200]}") from exc
        return [[float(x) for x in v] for v in vecs]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([BGE_QUERY_PREFIX + text])[0]


class FinetunedEmbedder(LocalEmbedder):
    """Same encoding rules as the base model (query prefix, normalised vectors); weights come from a directory."""

    def __init__(self, path: Path, model: Any | None = None, device: str | None = None) -> None:
        super().__init__(model=model, device=device)
        self._path = path
        self.model_id = (path / "model_id.txt").read_text().strip()

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    "local embedder needs the optional group: uv sync --group local-embed"
                ) from exc
            self._model = SentenceTransformer(
                str(self._path), device=self._device, trust_remote_code=False
            )
            got = self._model.get_sentence_embedding_dimension()
            if got != DIMS:
                raise EmbeddingError(f"fine-tuned model produced {got} dims, schema expects {DIMS}")
        return self._model


def make_embedder(name: str, *, api_key: str | None = None) -> Embedder:
    model_id_for(name)  # validates the name
    if name == "gemini":
        if not api_key:
            raise ValueError("GEMINI_API_KEY required for the gemini embedder")
        return GeminiEmbedder(api_key)
    if name == "finetuned":
        return FinetunedEmbedder(ft_model_dir())
    return LocalEmbedder()
