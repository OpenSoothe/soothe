"""Tests for Tacitus subagent factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from soothe.config import SootheConfig, SubagentConfig
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
    assert names == {"web_search", "academic_search", "url_crawl"}


def test_create_tacitus_subagent_accepts_resolver_kwargs() -> None:
    """Resolver must not pass YAML config keys (e.g. llm_role) as factory kwargs."""
    cfg = SootheConfig(
        subagents={
            "tacitus": SubagentConfig(
                config={"llm_role": "fast", "synthesis_role": "think"},
            ),
        },
    )
    mock_model = MagicMock()
    work_dir = "/tmp/tacitus-workspace"
    with patch(
        "soothe.subagents.tacitus.implementation.build_tacitus_engine",
        return_value=MagicMock(),
    ):
        result = create_tacitus_subagent(
            mock_model,
            cfg,
            {"work_dir": work_dir},
        )
    assert result["name"] == "tacitus"
