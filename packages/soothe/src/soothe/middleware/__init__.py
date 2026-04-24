"""Soothe middleware modules.

This package provides middleware implementations that wrap deepagents:
- SoothePolicyMiddleware: Enforce PolicyProtocol on tool/subagent calls
- SystemPromptOptimizationMiddleware: Dynamic prompt adjustment based on classification
- LLMRateLimitMiddleware: Rate limiting at LLM level, not thread level
- ExecutionHintsMiddleware: AgentLoop → CoreAgent execution hints injection
- WorkspaceContextMiddleware: Thread-aware workspace ContextVar management
- LLMTracingMiddleware: Trace LLM request/response lifecycle for debugging
- PerTurnModelMiddleware: Per-stream model override for daemon/TUI
- SootheFilesystemMiddleware: Extended filesystem tools middleware

Utility functions:
- create_llm_call_metadata: Create standardized metadata for LLM calls

Builder function:
- build_soothe_middleware_stack(): Construct middleware stack in correct order
"""

from soothe.middleware._builder import build_soothe_middleware_stack
from soothe.middleware._utils import create_llm_call_metadata
from soothe.middleware.execution_hints import ExecutionHintsMiddleware
from soothe.middleware.filesystem import SootheFilesystemMiddleware
from soothe.middleware.llm_rate_limit import LLMRateLimitMiddleware
from soothe.middleware.llm_tracing import LLMTracingMiddleware
from soothe.middleware.per_turn_model import PerTurnModelMiddleware
from soothe.middleware.policy import SoothePolicyMiddleware
from soothe.middleware.system_prompt_optimization import SystemPromptOptimizationMiddleware
from soothe.middleware.workspace_context import WorkspaceContextMiddleware

__all__ = [
    "ExecutionHintsMiddleware",
    "LLMRateLimitMiddleware",
    "LLMTracingMiddleware",
    "SootheFilesystemMiddleware",
    "SoothePolicyMiddleware",
    "SystemPromptOptimizationMiddleware",
    "PerTurnModelMiddleware",
    "WorkspaceContextMiddleware",
    "build_soothe_middleware_stack",
    "create_llm_call_metadata",
]
