"""Regression tests for explorer middleware stack construction."""

from __future__ import annotations

from types import SimpleNamespace

from langchain.agents.middleware import ToolCallLimitMiddleware, ToolRetryMiddleware

from soothe_nano.config import SootheConfig
from soothe_nano.subagents.explore.middleware import build_explore_middleware_stack
from soothe_nano.subagents.explore.schemas import ExploreSubagentConfig


def test_build_explorer_middleware_stack_includes_tool_limit_and_retry() -> None:
    cfg = SootheConfig()
    explore_cfg = ExploreSubagentConfig(
        tool_call_limit_thread=25,
        tool_call_limit_run=10,
    )

    stack = build_explore_middleware_stack(
        model=SimpleNamespace(),
        explore_config=explore_cfg,
        resolver_workspace="/tmp",
        max_iterations=6,
        max_matches=5,
        soothe_config=cfg,
    )

    limit = next(m for m in stack if isinstance(m, ToolCallLimitMiddleware))
    retry = next(m for m in stack if isinstance(m, ToolRetryMiddleware))
    assert limit.thread_limit == 25
    assert limit.run_limit == 10
    assert retry.max_retries == cfg.agent.middleware.tool_retry.max_retries
