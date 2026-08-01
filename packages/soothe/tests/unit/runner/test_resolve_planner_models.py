"""Tests for resolve_planner plan-phase model role wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe.config import SootheConfig
from soothe.runner.resolver import resolve_planner


def test_resolve_planner_uses_loop_plan_model_roles() -> None:
    cfg = SootheConfig(
        agent={
            "loop": {
                "plan_evaluate_assess_model_role": "fast",
                "plan_evaluate_gap_model_role": "default",
                "plan_generate_model_role": "think",
                "plan_generate_model_role_simple": "fast",
                "plan_generate_model_role_near_gap": "default",
            }
        }
    )
    assess_model = MagicMock(name="assess")
    gap_model = MagicMock(name="gap")
    generate_model = MagicMock(name="generate")
    base_model = MagicMock(name="base")

    with patch.object(
        SootheConfig,
        "create_chat_model",
        side_effect=lambda *args: {
            "fast": assess_model,
            "default": gap_model,
            "think": generate_model,
        }[args[-1]],
    ) as create_chat_model:
        planner = resolve_planner(cfg, base_model)

    roles = [call.args[-1] for call in create_chat_model.call_args_list]
    assert "fast" in roles
    assert "default" in roles
    assert "think" in roles
    assert planner._plan_evaluate_assess_model is assess_model
    assert planner._plan_evaluate_gap_model is gap_model
    assert planner._plan_generate_model is generate_model
    assert planner._plan_generate_model_simple is assess_model
    assert planner._plan_generate_model_near_gap is gap_model
    assert planner._model is base_model


def test_resolve_planner_defaults_gap_and_assess_to_fast() -> None:
    cfg = SootheConfig()
    assert cfg.agent.loop.plan_evaluate_assess_model_role == "fast"
    assert cfg.agent.loop.plan_evaluate_gap_model_role == "fast"
    assert cfg.agent.loop.plan_generate_model_role == "think"
    assert cfg.agent.loop.plan_generate_model_role_simple == "fast"
    assert cfg.agent.loop.plan_generate_model_role_near_gap == "fast"

    fast_model = MagicMock(name="fast")
    think_model = MagicMock(name="think")
    base_model = MagicMock(name="base")

    with patch.object(
        SootheConfig,
        "create_chat_model",
        side_effect=lambda *args: {
            "fast": fast_model,
            "think": think_model,
        }[args[-1]],
    ):
        planner = resolve_planner(cfg, base_model)

    assert planner._plan_evaluate_assess_model is fast_model
    assert planner._plan_evaluate_gap_model is fast_model
    assert planner._plan_generate_model is think_model
    assert planner._plan_generate_model_simple is fast_model
    assert planner._plan_generate_model_near_gap is fast_model
