"""Plan subagent factory (RFC-618)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.config import SubagentConfig

from .engine import build_plan_engine
from .schemas import PlanSubagentConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


def create_plan_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build the plan ``CompiledSubAgent`` spec.

    Args:
        model: Primary chat model for collection and plan-design loops (resolver always passes
            the router ``think`` role via ``create_chat_model("think")``).
        config: Soothe configuration.
        context: Must include ``work_dir`` for explore alignment with other subagents.

    Returns:
        Dict with ``name``, ``description``, and ``runnable`` graph.
    """
    from soothe.subagents.explore.implementation import create_explore_subagent

    work_dir = context.get("work_dir", "")
    sub_cfg = config.subagents.get("plan", SubagentConfig())
    plan_opts = PlanSubagentConfig(**sub_cfg.config)

    explore_model = config.create_chat_model("fast")
    explore_spec = create_explore_subagent(
        explore_model,
        config,
        {"work_dir": work_dir},
    )
    explore_runnable = explore_spec["runnable"]

    runnable = build_plan_engine(model, explore_runnable, plan_opts)

    return {
        "name": "plan",
        "description": (
            "Planning delegate with agentic loops: iteratively runs multiple readonly explore "
            "passes per round (and multiple collection rounds) to gather workspace evidence, then "
            "iteratively refines a full markdown execution plan before returning one report. "
            "Use when the main thread needs structured recon-plus-plan without doing every explore "
            "and rewrite itself."
        ),
        "runnable": runnable,
    }
