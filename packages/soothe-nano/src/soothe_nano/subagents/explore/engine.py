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

    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)


def build_explore_engine(
    model: BaseChatModel,
    config: ExploreSubagentConfig,
    workspace: str,
    *,
    allow_paths_outside_workspace: bool = False,
    synthesis_model: BaseChatModel | None = None,
    soothe_config: SootheConfig | None = None,
) -> Any:
    """Build the explore agent graph (``create_agent`` → ``CompiledStateGraph``).

    Args:
        model: LLM for search, assessment, and synthesis.
        config: Explore configuration (thoroughness, iteration caps).
        workspace: Search boundary (working directory / resolver default).
        allow_paths_outside_workspace: When False, sandbox tools to *workspace*.
        synthesis_model: Optional fast model for synthesis (defaults to model).
        soothe_config: Optional SootheConfig for tool middleware (limits, retries).

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
        synthesis_model=synthesis_model,
        soothe_config=soothe_config,
    )

    explore_preamble = (
        "You are Soothe's explore agent: use only read-only filesystem tools "
        "(glob, grep, ls, read_file, file_info). Full rules are in the system message each model turn."
    )

    graph = create_agent(
        model=model,
        tools=tools,
        system_prompt=explore_preamble,
        middleware=middleware,
        response_format=ExploreResult,
        state_schema=ExploreAgentState,
        name="explorer",
    )
    return graph.with_config(recursion_limit=int(config.recursion_limit))
