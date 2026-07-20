"""Soothe middleware modules.

This package provides middleware implementations:
- SoothePolicyMiddleware: Enforce PolicyProtocol on tool/subagent calls
- SystemPromptMiddleware: Dynamic prompt adjustment based on classification
- LLMRateLimitMiddleware: Rate limiting at LLM level, not thread level
- WorkspaceContextMiddleware: Thread-aware workspace ContextVar management
- PerTurnModelMiddleware: Per-stream model override for daemon/TUI
- SootheFilesystemMiddleware: Extended filesystem tools middleware
- CodeInterpreterMiddleware: Embedded QuickJS interpreter for programmatic tool calling (IG-423)
- MCPActivationMiddleware: MCP progressive disclosure search, promote, bind (RFC-412)
- ToolTimeoutMiddleware: Wrap tool calls with configurable timeout (IG-511)
- ToolEnforcementMiddleware: Request-time tool narrowing policies
- ToolOptimizationMiddleware: Deterministic lookup reuse/dedup/search-consolidation policy
- ProgressiveListingMiddleware: Prepare deferred listing blocks for system prompt

Utility functions:
- create_llm_call_metadata: Create standardized metadata for LLM calls

Builder function:
- build_soothe_middleware_stack(): Construct middleware stack in correct order
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe_deepagents.middleware.llm_rate_limit import LLMRateLimitMiddleware
    from soothe_deepagents.middleware.tool_timeout import ToolTimeoutMiddleware

    from soothe_nano.middleware._builder import (
        build_soothe_middleware_stack as build_soothe_middleware_stack,
    )
    from soothe_nano.middleware.code_interpreter import CodeInterpreterMiddleware
    from soothe_nano.middleware.filesystem import SootheFilesystemMiddleware
    from soothe_nano.middleware.mcp_activation import MCPActivationMiddleware
    from soothe_nano.middleware.model_call_profiler import (
        InnerModelCallProfilerMiddleware,
        LLMCallProfilerMiddleware,
        ModelCallProfilerMiddleware,
        install_model_call_profiler,
        is_profiler_enabled,
    )
    from soothe_nano.middleware.per_turn_model import PerTurnModelMiddleware
    from soothe_nano.middleware.policy import SoothePolicyMiddleware
    from soothe_nano.middleware.progressive_listing import ProgressiveListingMiddleware
    from soothe_nano.middleware.system_prompt import SystemPromptMiddleware
    from soothe_nano.middleware.tool_enforcement import ToolEnforcementMiddleware
    from soothe_nano.middleware.tool_optimization_middleware import ToolOptimizationMiddleware
    from soothe_nano.middleware.workspace_context import WorkspaceContextMiddleware
    from soothe_nano.utils.llm.observability import (
        create_llm_call_metadata as create_llm_call_metadata,
    )

__all__ = [
    "CodeInterpreterMiddleware",
    "InnerModelCallProfilerMiddleware",
    "LLMCallProfilerMiddleware",
    "LLMRateLimitMiddleware",
    "MCPActivationMiddleware",
    "ModelCallProfilerMiddleware",
    "SootheFilesystemMiddleware",
    "SoothePolicyMiddleware",
    "SystemPromptMiddleware",
    "PerTurnModelMiddleware",
    "ToolTimeoutMiddleware",
    "ToolEnforcementMiddleware",
    "ToolOptimizationMiddleware",
    "ProgressiveListingMiddleware",
    "WorkspaceContextMiddleware",
    "build_soothe_middleware_stack",
    "create_llm_call_metadata",
    "install_model_call_profiler",
    "is_profiler_enabled",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "build_soothe_middleware_stack": (
        "soothe_nano.middleware._builder",
        "build_soothe_middleware_stack",
    ),
    "CodeInterpreterMiddleware": (
        "soothe_nano.middleware.code_interpreter",
        "CodeInterpreterMiddleware",
    ),
    "create_llm_call_metadata": (
        "soothe_nano.utils.llm.observability",
        "create_llm_call_metadata",
    ),
    "SootheFilesystemMiddleware": (
        "soothe_nano.middleware.filesystem",
        "SootheFilesystemMiddleware",
    ),
    "LLMRateLimitMiddleware": (
        "soothe_deepagents.middleware.llm_rate_limit",
        "LLMRateLimitMiddleware",
    ),
    "MCPActivationMiddleware": ("soothe_nano.middleware.mcp_activation", "MCPActivationMiddleware"),
    "PerTurnModelMiddleware": ("soothe_nano.middleware.per_turn_model", "PerTurnModelMiddleware"),
    "SoothePolicyMiddleware": ("soothe_nano.middleware.policy", "SoothePolicyMiddleware"),
    "SystemPromptMiddleware": (
        "soothe_nano.middleware.system_prompt",
        "SystemPromptMiddleware",
    ),
    "ProgressiveListingMiddleware": (
        "soothe_nano.middleware.progressive_listing",
        "ProgressiveListingMiddleware",
    ),
    "ToolTimeoutMiddleware": (
        "soothe_deepagents.middleware.tool_timeout",
        "ToolTimeoutMiddleware",
    ),
    "ToolEnforcementMiddleware": (
        "soothe_nano.middleware.tool_enforcement",
        "ToolEnforcementMiddleware",
    ),
    "ToolOptimizationMiddleware": (
        "soothe_nano.middleware.tool_optimization_middleware",
        "ToolOptimizationMiddleware",
    ),
    "WorkspaceContextMiddleware": (
        "soothe_nano.middleware.workspace_context",
        "WorkspaceContextMiddleware",
    ),
    "ModelCallProfilerMiddleware": (
        "soothe_nano.middleware.model_call_profiler",
        "ModelCallProfilerMiddleware",
    ),
    "InnerModelCallProfilerMiddleware": (
        "soothe_nano.middleware.model_call_profiler",
        "InnerModelCallProfilerMiddleware",
    ),
    "LLMCallProfilerMiddleware": (
        "soothe_nano.middleware.model_call_profiler",
        "LLMCallProfilerMiddleware",
    ),
    "is_profiler_enabled": (
        "soothe_nano.middleware.model_call_profiler",
        "is_profiler_enabled",
    ),
    "install_model_call_profiler": (
        "soothe_nano.middleware.model_call_profiler",
        "install_model_call_profiler",
    ),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        module_path, attr = _LAZY_EXPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
