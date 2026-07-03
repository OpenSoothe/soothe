"""Tests for built-in Skillify subagent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe.config import SootheConfig
from soothe.subagents.skillify.implementation import create_skillify_subagent


def test_create_skillify_subagent_spec() -> None:
    config = SootheConfig()
    mock_vs = MagicMock()

    with patch.object(SootheConfig, "create_vector_store_for_role", return_value=mock_vs):
        with patch.object(SootheConfig, "create_embedding_model", return_value=MagicMock()):
            spec = create_skillify_subagent(None, config, {"work_dir": "/tmp"})

    assert spec["name"] == "skillify"
    assert "runnable" in spec
    assert "semantic search" in spec["description"].lower()
