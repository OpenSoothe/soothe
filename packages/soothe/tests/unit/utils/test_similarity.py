"""Unit tests for soothe.utils.similarity."""

from __future__ import annotations

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
    monkeypatch.setattr(sim, "_has_sentence_transformers", True)

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
    cache = tmp_path / "hf"
    monkeypatch.setattr(sim, "hf_embedding_cache_dir", lambda: cache)
    assert sim.is_embedding_model_cached_locally() is False


def test_is_embedding_model_cached_locally_true_with_snapshot(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "hf"
    snap = cache / "models--sentence-transformers--all-MiniLM-L6-v2" / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sim, "hf_embedding_cache_dir", lambda: cache)
    assert sim.is_embedding_model_cached_locally() is True
    assert sim.embedding_model_ready_without_download() is True
