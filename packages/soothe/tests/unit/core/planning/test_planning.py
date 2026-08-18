"""Tests for planning implementation (LLMPlanner)."""

from unittest.mock import MagicMock

from soothe.sloop.cognition.planner import LLMPlanner


class TestLLMPlanner:
    """Unit tests for LLMPlanner."""

    def test_initialization(self) -> None:
        """Test initialization with a model."""
        mock_model = MagicMock()
        planner = LLMPlanner(mock_model)

        assert planner._model == mock_model
