"""Tests for resolve_planner plan-phase model role wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe.config import SootheConfig
from soothe.runner.resolver import resolve_planner


def test_resolve_planner_uses_loop_plan_model_roles() -> None:
    cfg = SootheConfig(
        agent={
            "loop": {
                "plan_assess_model_role": "fast",
                "plan_generate_model_role": "think",
            }
        }
    )
    assess_model = MagicMock(name="assess")
    generate_model = MagicMock(name="generate")
    base_model = MagicMock(name="base")

    with patch.object(
        SootheConfig,
        "create_chat_model",
        side_effect=lambda *args: {
            "fast": assess_model,
            "think": generate_model,
        }[args[-1]],
    ) as create_chat_model:
        planner = resolve_planner(cfg, base_model)

    assert any(call.args[-1] == "fast" for call in create_chat_model.call_args_list)
    assert any(call.args[-1] == "think" for call in create_chat_model.call_args_list)
    assert planner._plan_assess_model is assess_model
    assert planner._plan_generate_model is generate_model
    assert planner._model is base_model
