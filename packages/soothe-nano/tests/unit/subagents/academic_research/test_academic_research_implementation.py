"""Tests for academic_research subagent factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from soothe_nano.config import SootheConfig, SubagentConfig
from soothe_nano.subagents.academic_research.implementation import create_academic_research_subagent


@pytest.fixture
def mock_model() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_config() -> MagicMock:
    return MagicMock(security=MagicMock(allow_paths_outside_workspace=False))


def test_create_academic_research_subagent_name(
    mock_model: MagicMock, mock_config: MagicMock
) -> None:
    with patch(
        "soothe_nano.subagents.academic_research.implementation.build_academic_research_engine",
        return_value=MagicMock(),
    ):
        result = create_academic_research_subagent(mock_model, mock_config, {})
    assert result["name"] == "academic_research"


def test_create_academic_research_academic_source_only(
    mock_model: MagicMock, mock_config: MagicMock
) -> None:
    from soothe_nano.subagents.academic_research.implementation import _build_academic_source

    source = _build_academic_source(mock_config)
    assert source.name == "academic_search"


def test_create_academic_research_subagent_accepts_resolver_kwargs() -> None:
    cfg = SootheConfig(
        subagents={
            "academic_research": SubagentConfig(
                config={"effort": "thorough"},
            ),
        },
    )
    mock_model = MagicMock()
    with patch(
        "soothe_nano.subagents.academic_research.implementation.build_academic_research_engine",
        return_value=MagicMock(),
    ) as build_mock:
        result = create_academic_research_subagent(mock_model, cfg, {})
    assert result["name"] == "academic_research"
    build_mock.assert_called_once()
