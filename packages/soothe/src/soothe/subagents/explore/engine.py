"""Explore engine — LangChain ``create_agent`` readonly filesystem search (RFC-613)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent

from .middleware import build_explore_middleware_stack
from .schemas import ExploreAgentState, ExploreResult, ExploreSubagentConfig
from .tools import get_explore_tools

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def build_explore_engine(
    model: BaseChatModel,
    config: ExploreSubagentConfig,
    workspace: str,
    *,
    allow_paths_outside_workspace: bool = False,
) -> Any:
    """Build the explore agent graph (``create_agent`` → ``CompiledStateGraph``).

    Args:
        model: LLM for search, assessment, and synthesis.
        config: Explore configuration (thoroughness, iteration caps).
        workspace: Search boundary (working directory / resolver default).
        allow_paths_outside_workspace: When False, sandbox tools to *workspace*.

    Returns:
        Compiled LangGraph runnable.
    """
    tools = get_explore_tools(
        workspace=workspace,
        allow_paths_outside_workspace=allow_paths_outside_workspace,
    )
    thoroughness = config.thoroughness
    max_iterations = config.max_iterations.get(thoroughness, 24)
    max_matches = config.max_matches_returned

    middleware = build_explore_middleware_stack(
        model,
        config,
        workspace,
        max_iterations=max_iterations,
        max_matches=max_matches,
    )

    graph = create_agent(
        model=model,
        tools=tools,
        system_prompt=(
            "You are Soothe's explore agent: every tool call must be read-only "
            "(including execute). Full rules are in the system message each model turn."
        ),
        middleware=middleware,
        response_format=ExploreResult,
        state_schema=ExploreAgentState,
        name="explore",
    )
    return graph
