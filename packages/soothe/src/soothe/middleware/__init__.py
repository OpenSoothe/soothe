"""Soothe middleware modules.

This package provides middleware implementations that wrap deepagents:
- SoothePolicyMiddleware: Enforce PolicyProtocol on tool/subagent calls
- SystemPromptOptimizationMiddleware: Dynamic prompt adjustment based on classification
- LLMRateLimitMiddleware: Rate limiting at LLM level, not thread level
- ExecutionHintsMiddleware: AgentLoop → CoreAgent execution hints injection
- WorkspaceContextMiddleware: Thread-aware workspace ContextVar management
- PerTurnModelMiddleware: Per-stream model override for daemon/TUI
- SootheFilesystemMiddleware: Extended filesystem tools middleware

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
    from soothe.middleware.execution_hints import ExecutionHintsMiddleware
    from soothe.middleware.filesystem import SootheFilesystemMiddleware
    from soothe.middleware.llm_rate_limit import LLMRateLimitMiddleware
    from soothe.middleware.per_turn_model import PerTurnModelMiddleware
    from soothe.middleware.policy import SoothePolicyMiddleware
    from soothe.middleware.system_prompt_optimization import SystemPromptOptimizationMiddleware
    from soothe.middleware.workspace_context import WorkspaceContextMiddleware

__all__ = [
    "ExecutionHintsMiddleware",
    "LLMRateLimitMiddleware",
    "SootheFilesystemMiddleware",
    "SoothePolicyMiddleware",
    "SystemPromptOptimizationMiddleware",
    "PerTurnModelMiddleware",
    "WorkspaceContextMiddleware",
    "build_soothe_middleware_stack",
    "create_llm_call_metadata",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "build_soothe_middleware_stack": (
        "soothe.middleware._builder",
        "build_soothe_middleware_stack",
    ),
    "create_llm_call_metadata": ("soothe.middleware._utils", "create_llm_call_metadata"),
    "ExecutionHintsMiddleware": ("soothe.middleware.execution_hints", "ExecutionHintsMiddleware"),
    "SootheFilesystemMiddleware": ("soothe.middleware.filesystem", "SootheFilesystemMiddleware"),
    "LLMRateLimitMiddleware": ("soothe.middleware.llm_rate_limit", "LLMRateLimitMiddleware"),
    "PerTurnModelMiddleware": ("soothe.middleware.per_turn_model", "PerTurnModelMiddleware"),
    "SoothePolicyMiddleware": ("soothe.middleware.policy", "SoothePolicyMiddleware"),
    "SystemPromptOptimizationMiddleware": (
        "soothe.middleware.system_prompt_optimization",
        "SystemPromptOptimizationMiddleware",
    ),
    "WorkspaceContextMiddleware": (
        "soothe.middleware.workspace_context",
        "WorkspaceContextMiddleware",
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
