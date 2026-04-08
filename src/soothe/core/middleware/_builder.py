"""Middleware stack construction for CoreAgent.

Defines the Soothe middleware layer that wraps deepagents.
Note: ParallelToolsMiddleware removed - langchain handles tool parallelism
via asyncio.gather in ToolNode.

This module provides a single function to build the middleware stack
in the correct order with proper dependency handling.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentMiddleware

    from soothe.config import SootheConfig
    from soothe.protocols.context import ContextProtocol
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)


def build_soothe_middleware_stack(
    config: SootheConfig,
    policy: PolicyProtocol | None,
    context: ContextProtocol | None,
) -> tuple[AgentMiddleware, ...]:
    """Build Soothe middleware stack in correct order.

    The middleware order is intentional and follows dependency requirements:

    1. **SoothePolicyMiddleware** - Blocks unsafe actions FIRST before any
       other middleware processes them. Uses PolicyProtocol.check() on every
       tool/subagent call.

    2. **SystemPromptOptimizationMiddleware** - Modifies prompts BEFORE the
       LLM call. Requires unified_classification state injected by Layer 2
       runner during pre-stream phase. Only enabled when performance features
       are fully configured.

    3. **LLMTracingMiddleware** - Traces LLM request/response lifecycle for
       debugging. Logs request details, response details, and latency metrics.
       Enabled via SOOTHE_LOG_LEVEL=DEBUG or config.llm_tracing.enabled=True.

    4. **ExecutionHintsMiddleware** - Injects Layer 2 execution hints
       (soothe_step_tools, soothe_step_subagent, soothe_step_expected_output)
       into system prompt via abefore_agent hook. Runs before agent loop starts.

    5. **WorkspaceContextMiddleware** - Sets workspace ContextVar via
       abefore_agent/aafter_agent hooks. Must be set before tools run to
       enable thread-aware filesystem operations.

    6. **SubagentContextMiddleware** - Injects context briefings into
       task tool delegations via awrap_tool_call hook. Provides subagents
       with scoped context projections from ContextProtocol.

    Note: Tool parallelism is handled by langchain's built-in asyncio.gather
    in ToolNode. No explicit ParallelToolsMiddleware needed.

    Args:
        config: SootheConfig with performance settings.
        policy: PolicyProtocol instance for safety enforcement.
        context: ContextProtocol instance for subagent briefing injection.

    Returns:
        Tuple of middleware instances in execution order.
    """
    from .execution_hints import ExecutionHintsMiddleware
    from .llm_tracing import LLMTracingMiddleware
    from .policy import SoothePolicyMiddleware
    from .subagent_context import SubagentContextMiddleware
    from .system_prompt_optimization import SystemPromptOptimizationMiddleware
    from .workspace_context import WorkspaceContextMiddleware

    stack: list[AgentMiddleware] = []

    # 1. Policy enforcement (must be first to block unsafe actions)
    if policy:
        stack.append(
            SoothePolicyMiddleware(
                policy=policy,
                profile_name=config.protocols.policy.profile,
            )
        )
        logger.debug("[Middleware] Policy enforcement enabled")

    # 2. System prompt optimization (requires unified_classification from Layer 2)
    # Only enabled when both performance flags are set
    if (
        config.performance.enabled
        and config.performance.optimize_system_prompts
        and config.performance.unified_classification
    ):
        stack.append(SystemPromptOptimizationMiddleware(config=config))
        logger.info("[Middleware] System prompt optimization enabled")

    # 3. LLM tracing (debug info for request/response lifecycle)
    # Enabled when logging level is DEBUG or explicitly configured
    import os

    log_level = os.environ.get("SOOTHE_LOG_LEVEL", "INFO")
    llm_tracing_enabled = log_level == "DEBUG" or (hasattr(config, "llm_tracing") and config.llm_tracing.enabled)
    if llm_tracing_enabled:
        preview_length = (
            getattr(config.llm_tracing, "log_preview_length", 200) if hasattr(config, "llm_tracing") else 200
        )
        stack.append(LLMTracingMiddleware(log_preview_length=preview_length))
        logger.debug("[Middleware] LLM tracing enabled")

        # Auto-configure logging level for LLM tracing module (IG-140)
        import logging

        llm_logger = logging.getLogger("soothe.core.middleware.llm_tracing")
        llm_logger.setLevel(logging.DEBUG)

    # 4. Execution hints (Layer 2 → Layer 1 integration)
    stack.append(ExecutionHintsMiddleware())
    logger.debug("[Middleware] Execution hints enabled")

    # 5. Workspace context (thread-aware filesystem)
    stack.append(WorkspaceContextMiddleware())
    logger.debug("[Middleware] Workspace context enabled")

    # 6. Subagent context briefing injection
    if context:
        stack.append(SubagentContextMiddleware(context=context))
        logger.debug("[Middleware] Subagent context briefing enabled")

    return tuple(stack)
