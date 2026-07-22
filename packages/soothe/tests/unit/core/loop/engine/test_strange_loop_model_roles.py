"""Tests for loop-phase model role resolution on StrangeLoop."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe.config import SootheConfig
from soothe.sloop.engine.strange_loop import StrangeLoop


def test_strange_loop_resolves_goal_synthesis_model_role() -> None:
    cfg = SootheConfig(
        agent={
            "loop": {
                "goal_synthesis_model_role": "fast",
            }
        }
    )
    planner = MagicMock()
    planner._model = MagicMock(name="planner-fallback")
    synthesis_model = MagicMock(name="synthesis")

    with patch.object(
        SootheConfig,
        "create_chat_model",
        side_effect=lambda *args: synthesis_model if args[-1] == "fast" else MagicMock(),
    ):
        loop = StrangeLoop(core_agent=MagicMock(), loop_planner=planner, config=cfg)

    assert loop._goal_synthesis_llm is synthesis_model
    assert loop.goal_synthesis_model() is synthesis_model
