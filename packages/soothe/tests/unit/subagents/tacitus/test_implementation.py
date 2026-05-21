"""Tests for Tacitus subagent factory."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.subagents.tacitus.implementation import create_tacitus_subagent


@pytest.fixture
def mock_model() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_config() -> MagicMock:
    return MagicMock(security=MagicMock(allow_paths_outside_workspace=False))


def test_create_tacitus_subagent_name(mock_model: MagicMock, mock_config: MagicMock) -> None:
    result = create_tacitus_subagent(mock_model, mock_config, {})
    assert result["name"] == "tacitus"


def test_create_tacitus_public_sources_only(mock_model: MagicMock, mock_config: MagicMock) -> None:
    from soothe.subagents.tacitus.implementation import _build_public_sources

    sources = _build_public_sources(mock_config)
    names = {s.capability_id for s in sources}
    assert names == {"web_search", "wikipedia", "academic_search", "url_crawl"}
