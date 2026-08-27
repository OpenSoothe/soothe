"""Protocol, subagent, and tool resolution logic for create_soothe_agent.

Protocol resolution (memory, planner, policy) lives here.
Tool/subagent/infrastructure resolution is delegated to ``soothe_nano.resolve``.
Host checkpointer / durability bindings live in ``_resolver_infra.py``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe_nano.resolve import (
    SUBAGENT_FACTORIES,
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


def resolve_planner(
    config: SootheConfig,
    model: BaseChatModel | None,
) -> PlannerProtocol | None:
    """Host planner resolution — always ``None``; the loop plans inline."""
    del config, model
    return None
