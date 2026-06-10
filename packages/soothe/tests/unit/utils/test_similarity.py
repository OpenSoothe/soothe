"""Unit tests for soothe.utils.similarity."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from soothe.utils import similarity as sim


def test_calculate_relevance_score_uses_semantic_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Relevance is derived from snippet similarity, not path keyword heuristics."""
    monkeypatch.setattr(sim, "embedding_model_ready_without_download", lambda: True)
    monkeypatch.setattr(sim, "semantic_similarity", lambda _a, _b: 0.85)

    finding = {"path": "/unrelated/path.txt", "snippet": "goal engine integration"}
    assert sim.calculate_relevance_score(finding, "agentloop", enable_semantic=True) == "high"


def test_calculate_relevance_score_without_model_returns_medium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sim, "embedding_model_ready_without_download", lambda: False)

    finding = {"path": "/pkg/goal_engine.py", "snippet": "class GoalEngine"}
    assert sim.calculate_relevance_score(finding, "goal", enable_semantic=True) == "medium"


def test_rank_by_similarity_skips_when_model_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items = [
        {"snippet": "b", "path": "/b"},
        {"snippet": "a", "path": "/a"},
    ]
    monkeypatch.setattr(sim, "embedding_model_ready_without_download", lambda: False)
    monkeypatch.setattr(sim, "_has_fastembed", True)

    with patch.object(sim, "log_skip_semantic_similarity") as log_skip:
        ranked = sim.rank_by_similarity(items, "target", enable_semantic=True)

    assert ranked is items
    log_skip.assert_called_once()


def test_rank_by_similarity_sorts_when_model_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [
        {"snippet": "low", "path": "/low"},
        {"snippet": "high", "path": "/high"},
    ]
    monkeypatch.setattr(sim, "embedding_model_ready_without_download", lambda: True)

    def fake_similarity(text1: str, _text2: str) -> float:
        return 0.9 if text1 == "high" else 0.1

    monkeypatch.setattr(sim, "semantic_similarity", fake_similarity)

    ranked = sim.rank_by_similarity(items, "target", enable_semantic=True)
    assert [i["snippet"] for i in ranked] == ["high", "low"]


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
