"""Embedder providers + factory — fakes only: no network, no model download, no torch."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from services import embeddings
from services.embeddings import (
    BGE_QUERY_PREFIX,
    DIMS,
    GEMINI_MODEL_ID,
    LOCAL_MODEL_ID,
    EmbeddingError,
    GeminiEmbedder,
    LocalEmbedder,
    make_embedder,
    model_id_for,
)


# ---------------------------------------------------------------- factory / tags
def test_model_ids_are_distinct_and_versioned() -> None:
    assert model_id_for("gemini") == GEMINI_MODEL_ID == "gemini-embedding-001@768"
    assert model_id_for("local") == LOCAL_MODEL_ID
    assert LOCAL_MODEL_ID.startswith("BAAI/bge-base-en-v1.5@")
    assert GEMINI_MODEL_ID != LOCAL_MODEL_ID


def test_unknown_embedder_rejected() -> None:
    with pytest.raises(ValueError, match="unknown embedder"):
        model_id_for("openai")
    with pytest.raises(ValueError):
        make_embedder("openai")


def test_gemini_needs_a_key_but_local_does_not() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        make_embedder("gemini")
    assert make_embedder("local").model_id == LOCAL_MODEL_ID  # lazy: no torch import yet


def test_pinned_revision_is_a_full_commit_hash() -> None:
    assert len(embeddings.LOCAL_REVISION) == 40
    assert all(c in "0123456789abcdef" for c in embeddings.LOCAL_REVISION)


# ---------------------------------------------------------------- local
class FakeSTModel:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append({"texts": texts, **kwargs})
        return [[0.5] * DIMS for _ in texts]


def test_local_documents_get_no_prefix_and_are_normalized() -> None:
    model = FakeSTModel()
    vecs = LocalEmbedder(model=model).embed_documents(["alpha", "beta"])
    assert len(vecs) == 2 and len(vecs[0]) == DIMS
    call = model.calls[0]
    assert call["texts"] == ["alpha", "beta"]  # passages: model card says NO instruction
    assert call["normalize_embeddings"] is True
    assert call["batch_size"] == 32


def test_local_query_gets_the_bge_instruction_prefix() -> None:
    model = FakeSTModel()
    LocalEmbedder(model=model).embed_query("customer concentration")
    assert model.calls[0]["texts"] == [BGE_QUERY_PREFIX + "customer concentration"]


def test_local_failure_is_wrapped_as_embedding_error() -> None:
    class Boom:
        def encode(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("MPS out of memory")

    with pytest.raises(EmbeddingError, match="out of memory"):
        LocalEmbedder(model=Boom()).embed_documents(["x"])


def test_local_has_no_pause_and_is_not_rate_limited() -> None:
    assert LocalEmbedder.pause_s == 0.0


# ---------------------------------------------------------------- gemini (fake client)
class FakeGeminiClient:
    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls = 0
        self.models = SimpleNamespace(embed_content=self._embed)

    def _embed(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls += 1
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        n = 1 if isinstance(contents, str) else len(contents)
        n = step if isinstance(step, int) else n
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * DIMS) for _ in range(n)])


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(embeddings.time, "sleep", slept.append)
    return slept


def test_gemini_retries_quota_then_succeeds(_no_real_sleep: list[float]) -> None:
    client = FakeGeminiClient([RuntimeError("429 RESOURCE_EXHAUSTED"), "ok"])
    e = GeminiEmbedder("k", client=client)
    assert len(e.embed_documents(["a", "b"])) == 2
    assert client.calls == 2
    assert _no_real_sleep == [embeddings.QUOTA_WAIT_S]  # waited out the minute window


def test_gemini_gives_up_after_max_attempts_with_embedding_error() -> None:
    client = FakeGeminiClient([RuntimeError("429")] * embeddings.GEMINI_MAX_ATTEMPTS)
    with pytest.raises(EmbeddingError, match="failed after"):
        GeminiEmbedder("k", client=client).embed_documents(["a"])


def test_gemini_count_mismatch_is_an_error() -> None:
    client = FakeGeminiClient(
        [1] * embeddings.GEMINI_MAX_ATTEMPTS
    )  # 1 vector for 2 texts, every time
    with pytest.raises(EmbeddingError):
        GeminiEmbedder("k", client=client).embed_documents(["a", "b"])


def test_gemini_query_wraps_failures() -> None:
    client = FakeGeminiClient([RuntimeError("network down")])
    with pytest.raises(EmbeddingError, match="query embedding failed"):
        GeminiEmbedder("k", client=client).embed_query("q")


def test_finetuned_embedder_takes_its_tag_from_the_checkpoint_directory(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    import pytest

    from services.embeddings import FinetunedEmbedder, make_embedder, model_id_for

    monkeypatch.delenv("EA_FT_MODEL_PATH", raising=False)
    with pytest.raises(ValueError, match="EA_FT_MODEL_PATH"):
        model_id_for("finetuned")
    (tmp_path / "model_id.txt").write_text("edgar-ft-bge-base@abc12345\n")
    monkeypatch.setenv("EA_FT_MODEL_PATH", str(tmp_path))
    assert model_id_for("finetuned") == "edgar-ft-bge-base@abc12345"
    emb = make_embedder("finetuned")
    assert isinstance(emb, FinetunedEmbedder) and emb.model_id == "edgar-ft-bge-base@abc12345"
    (tmp_path / "model_id.txt").write_text("something-else")
    with pytest.raises(ValueError, match="unexpected"):
        model_id_for("finetuned")


def test_genai_client_factory_picks_the_backend_from_the_environment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import pytest

    from services import genai_client as gc

    seen: dict[str, object] = {}

    class FakeGenai:
        class Client:
            def __init__(self, **kw: object) -> None:
                seen.update(kw)

    class FakeTypes:
        class HttpOptions:
            def __init__(self, timeout: int) -> None:
                self.timeout = timeout

    import sys
    import types as pytypes

    google = pytypes.ModuleType("google")
    google.genai = FakeGenai  # type: ignore[attr-defined]
    FakeGenai.types = FakeTypes  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", FakeGenai)
    monkeypatch.setitem(sys.modules, "google.genai.types", FakeTypes)

    monkeypatch.delenv("EA_GENAI_BACKEND", raising=False)
    gc.make_genai_client("key123")
    assert seen == {"api_key": "key123"}

    seen.clear()
    monkeypatch.setenv("EA_GENAI_BACKEND", "vertex")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    with pytest.raises(ValueError, match="GOOGLE_CLOUD_PROJECT"):
        gc.make_genai_client("ignored")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-proj")
    gc.make_genai_client("ignored")
    assert seen["vertexai"] is True and seen["project"] == "my-proj" and "api_key" not in seen
