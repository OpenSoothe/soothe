"""Soothe middleware for CoreAgent (Layer 1 runtime).

This package provides middleware implementations that wrap deepagents:
- SoothePolicyMiddleware: Enforce PolicyProtocol on tool/subagent calls
- SystemPromptOptimizationMiddleware: Dynamic prompt adjustment based on classification
- ExecutionHintsMiddleware: Layer 2 → Layer 1 execution hints injection
- WorkspaceContextMiddleware: Thread-aware workspace ContextVar management
- LLMTracingMiddleware: Trace LLM request/response lifecycle for debugging

Utility functions (IG-143):
- create_llm_call_metadata: Create standardized metadata for LLM calls

Builder function:
- build_soothe_middleware_stack(): Construct middleware stack in correct order
"""

from ._builder import build_soothe_middleware_stack
from ._utils import create_llm_call_metadata
from .execution_hints import ExecutionHintsMiddleware
from .llm_tracing import LLMTracingMiddleware
from .per_turn_model import PerTurnModelMiddleware
from .policy import SoothePolicyMiddleware
from .system_prompt_optimization import SystemPromptOptimizationMiddleware
from .workspace_context import WorkspaceContextMiddleware

__all__ = [
    "ExecutionHintsMiddleware",
    "LLMTracingMiddleware",
    "SoothePolicyMiddleware",
    "SystemPromptOptimizationMiddleware",
    "PerTurnModelMiddleware",
    "WorkspaceContextMiddleware",
    "build_soothe_middleware_stack",
    "create_llm_call_metadata",  # IG-143: Export metadata helper
]
