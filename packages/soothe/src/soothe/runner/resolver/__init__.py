"""Protocol, subagent, and tool resolution logic for create_soothe_agent.

Protocol resolution (memory, planner, policy) lives here.
Tool/subagent/infrastructure resolution is delegated to ``soothe_nano.resolve``
; only ``resolve_planner`` (host-specific ``LLMPlanner``) and the checkpointer
/durability bindings (``_resolver_infra.py``, ``shared_checkpointer_pool.py``)
are defined locally.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe_nano.resolve import (
    SUBAGENT_FACTORIES,
    _create_loop_phase_model,
    resolve_memory,
    resolve_policy,
    resolve_subagents,
    resolve_tools,
)

from soothe.config import SootheConfig

from ._resolver_infra import resolve_checkpointer, resolve_durability

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from soothe_sdk.protocols.planner import PlannerProtocol

logger = logging.getLogger(__name__)

__all__ = [
    "SUBAGENT_FACTORIES",
    "resolve_checkpointer",
    "resolve_durability",
    "resolve_memory",
    "resolve_planner",
    "resolve_policy",
    "resolve_subagents",
    "resolve_tools",
]


# ---------------------------------------------------------------------------
# Protocol resolution (memory, planner, policy)
#
# ``resolve_memory``, ``resolve_policy``, ``_create_loop_phase_model``,
# ``SUBAGENT_FACTORIES``, ``resolve_subagents``, and ``resolve_tools`` are
# imported from ``soothe_nano.resolve`` — they are byte-identical to the
# previous local copies.  Only ``resolve_planner`` diverges (host returns an
# ``LLMPlanner`` instance rather than ``None``), so it stays local.
# ---------------------------------------------------------------------------


def resolve_planner(
    config: SootheConfig,
    model: BaseChatModel | None,
) -> PlannerProtocol:
    """Instantiate LLMPlanner as the sole planner implementation.

    Args:
        config: Soothe configuration.
        model: The resolved chat model.

    Returns:
        LLMPlanner instance.
    """
    planner_role = config.agent.protocols.planner.model or "think"
    planner_model = model
    if planner_model is None:
        try:
            planner_model = config.create_chat_model(planner_role)
        except Exception:
            logger.warning("Failed to create model for planner")

    loop_cfg = config.agent.loop
    plan_assess_model = _create_loop_phase_model(
        config,
        loop_cfg.plan_assess_model_role,
        fallback=planner_model,
        phase="plan-assess",
    )
    plan_gap_model = _create_loop_phase_model(
        config,
        loop_cfg.plan_gap_model_role,
        fallback=plan_assess_model,
        phase="plan-gap-analysis",
    )
    plan_generate_model = _create_loop_phase_model(
        config,
        loop_cfg.plan_generate_model_role,
        fallback=planner_model,
        phase="plan-generate",
    )

    from soothe.sloop.cognition.planner import LLMPlanner

    return LLMPlanner(
        model=planner_model,
        config=config,
        plan_assess_model=plan_assess_model,
        plan_generate_model=plan_generate_model,
        plan_gap_model=plan_gap_model,
    )
