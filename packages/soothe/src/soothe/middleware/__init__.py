"""Soothe middleware modules.

This package provides middleware implementations:
- IdentityMiddleware: JWT token validation / external identity resolution (RFC-307)
- SoothePolicyMiddleware: Enforce PolicyProtocol on tool/subagent calls
- SystemPromptMiddleware: Dynamic prompt adjustment based on classification
- LLMRateLimitMiddleware: Rate limiting at LLM level, not thread level
- WorkspaceContextMiddleware: Thread-aware workspace ContextVar management
- PerTurnModelMiddleware: Per-stream model override for daemon/TUI
- SootheFilesystemMiddleware: Extended filesystem tools middleware
- CodeInterpreterMiddleware: Embedded QuickJS interpreter for programmatic tool calling (IG-423)
- MCPActivationMiddleware: MCP progressive disclosure search, promote, bind (RFC-412)
- ToolTimeoutMiddleware: Wrap tool calls with configurable timeout (IG-511)

Utility functions:
- create_llm_call_metadata: Create standardized metadata for LLM calls

Builder function:
- build_soothe_middleware_stack(): Construct middleware stack in correct order
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.middleware._builder import (
        build_soothe_middleware_stack as build_soothe_middleware_stack,
    )
    from soothe.middleware._utils import create_llm_call_metadata as create_llm_call_metadata
    from soothe.middleware.code_interpreter import CodeInterpreterMiddleware
    from soothe.middleware.filesystem import SootheFilesystemMiddleware
    from soothe.middleware.identity import IdentityMiddleware
    from soothe.middleware.llm_rate_limit import LLMRateLimitMiddleware
    from soothe.middleware.mcp_activation import MCPActivationMiddleware
    from soothe.middleware.model_call_profiler import (
        InnerModelCallProfilerMiddleware,
        LLMCallProfilerMiddleware,
        ModelCallProfilerMiddleware,
        install_model_call_profiler,
        is_profiler_enabled,
    )
    from soothe.middleware.per_turn_model import PerTurnModelMiddleware
    from soothe.middleware.policy import SoothePolicyMiddleware
    from soothe.middleware.system_prompt import SystemPromptMiddleware
    from soothe.middleware.tool_timeout import ToolTimeoutMiddleware
    from soothe.middleware.workspace_context import WorkspaceContextMiddleware

__all__ = [
    "AKSKConfig",
    "CodeInterpreterMiddleware",
    "IdentityConfig",
    "IdentityMiddleware",
    "IdentityRuntime",
    "InnerModelCallProfilerMiddleware",
    "LLMCallProfilerMiddleware",
    "LLMRateLimitMiddleware",
    "MCPActivationMiddleware",
    "ModelCallProfilerMiddleware",
    "SootheFilesystemMiddleware",
    "SoothePolicyMiddleware",
    "SystemPromptMiddleware",
    "PerTurnModelMiddleware",
    "TokenConfig",
    "ThreadContextProvider",
    "ToolTimeoutMiddleware",
    "WorkspaceContextMiddleware",
    "build_soothe_middleware_stack",
    "create_llm_call_metadata",
    "install_model_call_profiler",
    "is_profiler_enabled",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AKSKConfig": ("soothe.middleware.identity", "AKSKConfig"),
    "build_soothe_middleware_stack": (
        "soothe.middleware._builder",
        "build_soothe_middleware_stack",
    ),
    "CodeInterpreterMiddleware": (
        "soothe.middleware.code_interpreter",
        "CodeInterpreterMiddleware",
    ),
    "create_llm_call_metadata": ("soothe.middleware._utils", "create_llm_call_metadata"),
    "SootheFilesystemMiddleware": ("soothe.middleware.filesystem", "SootheFilesystemMiddleware"),
    "IdentityConfig": ("soothe.middleware.identity", "IdentityConfig"),
    "IdentityMiddleware": ("soothe.middleware.identity", "IdentityMiddleware"),
    "IdentityRuntime": ("soothe.middleware.identity", "IdentityRuntime"),
    "LLMRateLimitMiddleware": ("soothe.middleware.llm_rate_limit", "LLMRateLimitMiddleware"),
    "MCPActivationMiddleware": ("soothe.middleware.mcp_activation", "MCPActivationMiddleware"),
    "PerTurnModelMiddleware": ("soothe.middleware.per_turn_model", "PerTurnModelMiddleware"),
    "SoothePolicyMiddleware": ("soothe.middleware.policy", "SoothePolicyMiddleware"),
    "SystemPromptMiddleware": (
        "soothe.middleware.system_prompt",
        "SystemPromptMiddleware",
    ),
    "TokenConfig": ("soothe.middleware.identity", "TokenConfig"),
    "ThreadContextProvider": ("soothe.middleware.identity", "ThreadContextProvider"),
    "ToolTimeoutMiddleware": ("soothe.middleware.tool_timeout", "ToolTimeoutMiddleware"),
    "WorkspaceContextMiddleware": (
        "soothe.middleware.workspace_context",
        "WorkspaceContextMiddleware",
    ),
    "ModelCallProfilerMiddleware": (
        "soothe.middleware.model_call_profiler",
        "ModelCallProfilerMiddleware",
    ),
    "InnerModelCallProfilerMiddleware": (
        "soothe.middleware.model_call_profiler",
        "InnerModelCallProfilerMiddleware",
    ),
    "LLMCallProfilerMiddleware": (
        "soothe.middleware.model_call_profiler",
        "LLMCallProfilerMiddleware",
    ),
    "is_profiler_enabled": (
        "soothe.middleware.model_call_profiler",
        "is_profiler_enabled",
    ),
    "install_model_call_profiler": (
        "soothe.middleware.model_call_profiler",
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
