"""Tests for embedding router role health check."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from soothe_daemon.health.checks import embedding_role_check as erc
from soothe_daemon.health.models import CheckStatus


@pytest.mark.asyncio
async def test_embedding_role_skipped_without_config() -> None:
    result = await erc.check_embedding_role(None)
    assert result.category == "models"
    assert result.checks[0].name == "embedding_role_configured"
    assert result.checks[0].status == CheckStatus.SKIPPED


@pytest.mark.asyncio
async def test_embedding_role_warning_when_unset() -> None:
    config = SimpleNamespace(
        router=SimpleNamespace(embedding=None, default="openai:gpt-4o-mini"),
        embedding_dims=1536,
        resolve_model=lambda role: (
            "openai:gpt-4o-mini" if role == "embedding" else "openai:gpt-4o-mini"
        ),
    )
    result = await erc.check_embedding_role(config)
    assert result.checks[0].status == CheckStatus.WARNING
    assert "not set" in result.checks[0].message


@pytest.mark.asyncio
async def test_embedding_role_ok_when_configured() -> None:
    config = SimpleNamespace(
        router=SimpleNamespace(
            embedding="dashscope:text-embedding-v4",
            default="openai:gpt-4o-mini",
        ),
        skillify=SimpleNamespace(model_role="embedding"),
        embedding_dims=1024,
        resolve_model=lambda role: (
            "dashscope:text-embedding-v4" if role == "embedding" else "openai:gpt-4o-mini"
        ),
    )
    result = await erc.check_embedding_role(config)
    assert result.checks[0].status == CheckStatus.OK
    assert "text-embedding-v4" in result.checks[0].message


@pytest.mark.asyncio
async def test_embedding_role_reports_custom_skillify_model_role() -> None:
    config = SimpleNamespace(
        router=SimpleNamespace(
            embedding="dashscope:text-embedding-v4",
            default="openai:gpt-4o-mini",
        ),
        skillify=SimpleNamespace(model_role="fast"),
        embedding_dims=1024,
        resolve_model=lambda role: (
            "dashscope:text-embedding-v4"
            if role == "embedding"
            else ("dashscope:fast-embed" if role == "fast" else "openai:gpt-4o-mini")
        ),
    )
    result = await erc.check_embedding_role(config)
    details = result.checks[0].details or {}
    assert result.checks[0].status == CheckStatus.OK
    assert details["skillify_model_role"] == "fast"
    assert details["skillify_resolved"] == "dashscope:fast-embed"
