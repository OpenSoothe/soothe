"""Tests for embedding model warmup health check."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from soothe.daemon.health.checks import embedding_warmup_check as ew
from soothe.daemon.health.models import CheckStatus

_REAL_FIND_SPEC = importlib.util.find_spec


def _find_spec_no_sentence_transformers(name: str):
    if name == "sentence_transformers":
        return None
    return _REAL_FIND_SPEC(name)


def _find_spec_sentence_transformers_installed(name: str):
    if name == "sentence_transformers":
        return object()  # non-None sentinel
    return _REAL_FIND_SPEC(name)


@pytest.mark.asyncio
async def test_embedding_warmup_skipped_without_sentence_transformers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "soothe.daemon.health.checks.embedding_warmup_check.importlib.util.find_spec",
        _find_spec_no_sentence_transformers,
    )
    result = await ew.check_embedding_warmup()
    assert result.category == "models"
    assert len(result.checks) == 1
    assert result.checks[0].name == "embedding_model_warmup"
    assert result.checks[0].status == CheckStatus.SKIPPED


@pytest.mark.asyncio
async def test_embedding_warmup_warning_empty_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "soothe.daemon.health.checks.embedding_warmup_check.importlib.util.find_spec",
        _find_spec_sentence_transformers_installed,
    )
    monkeypatch.setattr(
        "soothe.utils.similarity.hf_embedding_cache_dir",
        lambda: tmp_path / "hf",
    )
    result = await ew.check_embedding_warmup()
    assert result.checks[0].status == CheckStatus.WARNING
    assert "warmup" in result.checks[0].details.get("remediation", "").lower()


@pytest.mark.asyncio
async def test_embedding_warmup_ok_when_weights_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "soothe.daemon.health.checks.embedding_warmup_check.importlib.util.find_spec",
        _find_spec_sentence_transformers_installed,
    )
    cache = tmp_path / "hf"
    cache.mkdir(parents=True)
    (cache / "model.safetensors").write_bytes(b"x")
    monkeypatch.setattr(
        "soothe.utils.similarity.hf_embedding_cache_dir",
        lambda: cache,
    )
    result = await ew.check_embedding_warmup()
    assert result.checks[0].status == CheckStatus.OK


def test_embedding_cache_looks_populated_suffix_case(tmp_path: Path) -> None:
    cache = tmp_path / "c"
    cache.mkdir()
    (cache / "w.BIN").write_bytes(b"1")
    assert ew._embedding_cache_looks_populated(cache) is True
