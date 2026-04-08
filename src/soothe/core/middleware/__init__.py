"""Soothe middleware for CoreAgent (Layer 1 runtime).

This package provides middleware implementations that wrap deepagents:
- SoothePolicyMiddleware: Enforce PolicyProtocol on tool/subagent calls
- SubagentContextMiddleware: Inject context briefings into subagent delegations
- SystemPromptOptimizationMiddleware: Dynamic prompt adjustment based on classification
- ExecutionHintsMiddleware: Layer 2 → Layer 1 execution hints injection
- WorkspaceContextMiddleware: Thread-aware workspace ContextVar management
- LLMTracingMiddleware: Trace LLM request/response lifecycle for debugging

Builder function:
- build_soothe_middleware_stack(): Construct middleware stack in correct order
"""

from ._builder import build_soothe_middleware_stack
from .execution_hints import ExecutionHintsMiddleware
from .llm_tracing import LLMTracingMiddleware
from .policy import SoothePolicyMiddleware
from .subagent_context import SubagentContextMiddleware
from .system_prompt_optimization import SystemPromptOptimizationMiddleware
from .workspace_context import WorkspaceContextMiddleware

__all__ = [
    "ExecutionHintsMiddleware",
    "LLMTracingMiddleware",
    "SoothePolicyMiddleware",
    "SubagentContextMiddleware",
    "SystemPromptOptimizationMiddleware",
    "WorkspaceContextMiddleware",
    "build_soothe_middleware_stack",
]
