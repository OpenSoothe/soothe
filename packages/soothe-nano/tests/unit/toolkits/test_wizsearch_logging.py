"""Unit tests for wizsearch lifecycle logging."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe_nano.toolkits._internal import wizsearch as wiz_internal

_TAVILY_ENV = patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}, clear=False)


def test_normalize_proxy_url_adds_scheme() -> None:
    assert wiz_internal.normalize_proxy_url("127.0.0.1:7890") == "http://127.0.0.1:7890"
    assert wiz_internal.normalize_proxy_url("http://127.0.0.1:7890") == "http://127.0.0.1:7890"
    assert wiz_internal.normalize_proxy_url(None) is None
    assert wiz_internal.normalize_proxy_url("  ") is None


def test_wizsearch_proxy_env_sets_and_restores() -> None:
    for key in wiz_internal._PROXY_ENV_KEYS:
        os.environ.pop(key, None)
    try:
        with wiz_internal.wizsearch_proxy_env("127.0.0.1:7890") as effective:
            assert effective == "http://127.0.0.1:7890"
            assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:7890"
            assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:7890"
        assert "HTTPS_PROXY" not in os.environ
        assert "HTTP_PROXY" not in os.environ
    finally:
        for key in wiz_internal._PROXY_ENV_KEYS:
            os.environ.pop(key, None)


def test_wizsearch_proxy_env_preserves_existing() -> None:
    with patch.dict(os.environ, {"HTTPS_PROXY": "http://existing:1"}, clear=False):
        with wiz_internal.wizsearch_proxy_env("http://127.0.0.1:7890") as effective:
            assert effective == "http://existing:1"
            assert os.environ["HTTPS_PROXY"] == "http://existing:1"


@pytest.mark.asyncio
async def test_perform_wizsearch_search_logs_start_and_done(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Search logs lifecycle lines when wizsearch returns results."""
    caplog.set_level("INFO", logger="soothe_nano.toolkits._internal.wizsearch")

    mock_result = MagicMock()
    mock_result.query = "world cup teams"
    mock_result.answer = None
    mock_result.response_time = 2.5
    mock_result.metadata = {
        "engine_status": {"tavily": {"engine": "tavily", "status": "success", "result_count": 2}}
    }
    mock_result.sources = [
        MagicMock(title="A", url="https://a.example", content="snippet a"),
        MagicMock(title="B", url="https://b.example", content="snippet b"),
    ]

    with (
        _TAVILY_ENV,
        patch.object(wiz_internal, "_check_wizsearch_available", return_value=True),
        patch.object(wiz_internal, "_maybe_apply_tavily_key"),
        patch("wizsearch.WizSearch") as mock_cls,
        patch("wizsearch.WizSearchConfig"),
        patch("soothe_nano.utils.output_capture.capture_subagent_output"),
    ):
        mock_cls.return_value.search = AsyncMock(return_value=mock_result)
        await wiz_internal.perform_wizsearch_search(
            query="world cup teams",
            engines=["tavily"],
            max_results_per_engine=5,
            timeout_seconds=30,
        )

    messages = [r.message for r in caplog.records]
    assert any("[Wizsearch] search start" in m for m in messages)
    assert any("[Wizsearch] search done" in m for m in messages)
    assert any("[Wizsearch] engine tavily:" in m for m in messages)


@pytest.mark.asyncio
async def test_perform_wizsearch_search_logs_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Search logs failure with elapsed time when wizsearch raises."""
    caplog.set_level("WARNING", logger="soothe_nano.toolkits._internal.wizsearch")

    with (
        _TAVILY_ENV,
        patch.object(wiz_internal, "_check_wizsearch_available", return_value=True),
        patch.object(wiz_internal, "_maybe_apply_tavily_key"),
        patch("wizsearch.WizSearch") as mock_cls,
        patch("wizsearch.WizSearchConfig"),
        patch("soothe_nano.utils.output_capture.capture_subagent_output"),
    ):
        mock_cls.return_value.search = AsyncMock(side_effect=RuntimeError("network down"))
        result = await wiz_internal.perform_wizsearch_search(
            query="timeout query",
            engines=["tavily"],
        )

    assert "Search failed" in result
    assert any("[Wizsearch] search failed" in r.message for r in caplog.records)
