"""Plan subagent factory (RFC-618)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe_nano.config import SubagentConfig

from .engine import build_plan_engine
from .schemas import PlanSubagentConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)


def create_plan_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Build the plan ``CompiledSubAgent`` spec.

    Args:
        model: Primary chat model for plan-design loops (resolver passes
            ``subagents.planner.model`` when set, else ``model_role``, default ``think``).
        config: Soothe configuration.
        context: Optional resolver context (``work_dir`` ignored; kept for API parity).

    Returns:
        Dict with ``name``, ``description``, and ``runnable`` graph.
    """
    _ = context.get("work_dir", "")
    sub_cfg = config.subagents.get("planner", SubagentConfig())
    plan_opts = PlanSubagentConfig(**sub_cfg.config)

    runnable = build_plan_engine(model, plan_opts, soothe_config=config)

    return {
        "name": "planner",
        "description": (
            "Planning delegate with agentic plan-design loops: iteratively refines a full "
            "markdown execution plan before returning one report. Use when the main thread "
            "needs structured planning; readonly recon belongs on execute-step threads."
        ),
        "runnable": runnable,
    }
