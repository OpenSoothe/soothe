"""Unit tests for soothe.utils.similarity."""

from __future__ import annotations

import asyncio

import pytest

from soothe.utils import similarity as sim


def test_is_embedding_model_cached_locally_false_when_empty(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "embeddings"
    monkeypatch.setattr(sim, "embedding_cache_dir", lambda: cache)
    assert sim.is_embedding_model_cached_locally() is False


@pytest.mark.asyncio
async def test_async_get_embedding_model_uses_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model load on a running loop must not call blocking Future.result on the loop thread."""
    sentinel = object()
    monkeypatch.setattr(sim, "_has_fastembed", True)
    monkeypatch.setattr(sim, "_embedding_model", None)
    monkeypatch.setattr(sim, "_model_loading_attempted", False)
    monkeypatch.setattr(sim, "_model_load_async_lock", None)
    monkeypatch.setattr(sim, "_load_embedding_model_in_thread", lambda: sentinel)

    ran_in_executor = False

    async def track_wait_for(awaitable, timeout):  # type: ignore[no-untyped-def]
        nonlocal ran_in_executor
        ran_in_executor = True
        return await awaitable

    monkeypatch.setattr(sim.asyncio, "wait_for", track_wait_for)

    result = await sim.async_get_embedding_model()
    assert result is sentinel
    assert ran_in_executor


def test_get_embedding_model_refuses_running_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _probe() -> None:
        monkeypatch.setattr(sim, "_model_loading_attempted", False)
        monkeypatch.setattr(sim, "_embedding_model", None)
        assert sim.get_embedding_model() is None

    asyncio.run(_probe())


def test_is_embedding_model_cached_locally_true_with_onnx(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "embeddings"
    model_dir = cache / "models--qdrant--all-MiniLM-L6-v2-onnx"
    model_dir.mkdir(parents=True)
    (model_dir / "model.onnx").write_bytes(b"onnx")
    monkeypatch.setattr(sim, "embedding_cache_dir", lambda: cache)
    monkeypatch.setattr(sim, "_has_fastembed", True)
    assert sim.is_embedding_model_cached_locally() is True
    assert sim.embedding_model_ready_without_download() is True
