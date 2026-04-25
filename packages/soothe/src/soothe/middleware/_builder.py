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
    from soothe.core.tool_context_registry import ToolContextRegistry
    from soothe.core.tool_trigger_registry import ToolTriggerRegistry
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)


def _build_tool_registries(
    config: SootheConfig,
) -> tuple[ToolTriggerRegistry | None, ToolContextRegistry | None]:
    """Create tool trigger and context registries.

    Args:
        config: Soothe configuration.

    Returns:
        Tuple of (trigger_registry, context_registry), or (None, None) if not configured.
    """
    # Only create registries if system prompt optimization is enabled
    if not config.performance.enabled or not config.performance.optimize_system_prompts:
        return None, None

    try:
        from soothe.core.tool_context_registry import ToolContextRegistry
        from soothe.core.tool_trigger_registry import ToolTriggerRegistry
        from soothe.plugin.global_registry import get_plugin_registry

        plugin_registry = get_plugin_registry()

        trigger_registry = ToolTriggerRegistry(plugin_registry)
        context_registry = ToolContextRegistry(config, plugin_registry)

        logger.debug("[Middleware] Tool registries created for dynamic context injection")
        return trigger_registry, context_registry
    except RuntimeError:
        # Plugin registry not initialized, skip tool registries
        logger.debug(
            "[Middleware] Plugin registry not available, dynamic context injection disabled"
        )
        return None, None


def build_soothe_middleware_stack(
    config: SootheConfig,
    policy: PolicyProtocol | None,
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

    3. **LLMRateLimitMiddleware** - Rate limits LLM API calls at model level,
       not thread level. Uses sliding window for RPM and semaphore for concurrent
       requests. Solves thread hanging issues from thread-level blocking.

    4. **LLMTracingMiddleware** - Traces LLM request/response lifecycle for
       debugging. Logs request details, response details, and latency metrics.
       Enabled via SOOTHE_LOG_LEVEL=DEBUG or config.llm_tracing.enabled=True.

    5. **ExecutionHintsMiddleware** - Injects Layer 2 execution hints
       (soothe_step_tools, soothe_step_subagent, soothe_step_expected_output)
       into system prompt via abefore_agent hook. Runs before agent loop starts.

    6. **WorkspaceContextMiddleware** - Sets workspace ContextVar via
       abefore_agent/aafter_agent hooks. Must be set before tools run to
       enable thread-aware filesystem operations.

    7. **PerTurnModelMiddleware** - When ``attach_stream_model_override`` is set
       for the current asyncio Task (daemon per-turn ``input``), replaces the
       chat model for that stream via ``ModelRequest.override``.

    Note: Tool parallelism is handled by langchain's built-in asyncio.gather
    in ToolNode. No explicit ParallelToolsMiddleware needed.

    Args:
        config: SootheConfig with performance settings.
        policy: PolicyProtocol instance for safety enforcement.

    Returns:
        Tuple of middleware instances in execution order.
    """
    from .execution_hints import ExecutionHintsMiddleware
    from .llm_rate_limit import LLMRateLimitMiddleware
    from .llm_tracing import LLMTracingMiddleware
    from .per_turn_model import PerTurnModelMiddleware
    from .policy import SoothePolicyMiddleware
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
        # Create tool registries for dynamic context injection (RFC-210)
        trigger_registry, context_registry = _build_tool_registries(config)

        stack.append(
            SystemPromptOptimizationMiddleware(
                config=config,
                tool_trigger_registry=trigger_registry,
                tool_context_registry=context_registry,
            )
        )
        logger.info("[Middleware] System prompt optimization enabled")

    # 3. LLM rate limiting (throttles API calls, not threads)
    # This prevents thread hanging by blocking only LLM calls, not entire threads
    # IG-053: Add timeout to prevent semaphore monopolization
    # IG-258 Phase 2: Thread-local rate limiting (parameter name change)
    rpm = getattr(config.performance, "llm_rpm_limit", 120)
    concurrent = getattr(config.performance, "llm_concurrent_limit", 10)
    timeout = getattr(config.performance, "llm_call_timeout_seconds", 60)
    stack.append(
        LLMRateLimitMiddleware(
            requests_per_minute=rpm,
            max_concurrent_requests_per_thread=concurrent,  # IG-258 Phase 2
            call_timeout_seconds=timeout,
            thread_local=True,  # IG-258 Phase 2: Enable thread-local budgets
        )
    )
    logger.info(
        "[Middleware] LLM rate limiting enabled (thread-local): rpm=%d, concurrent=%d, timeout=%ds",
        rpm,
        concurrent,
        timeout,
    )

    # 4. LLM tracing (debug info for request/response lifecycle)
    # Enabled when logging level is DEBUG or explicitly configured
    import os

    log_level = os.environ.get("SOOTHE_LOG_LEVEL", "INFO")
    llm_tracing_enabled = log_level == "DEBUG" or (
        hasattr(config, "llm_tracing") and config.llm_tracing.enabled
    )
    if llm_tracing_enabled:
        preview_length = (
            getattr(config.llm_tracing, "log_preview_length", 200)
            if hasattr(config, "llm_tracing")
            else 200
        )
        stack.append(LLMTracingMiddleware(log_preview_length=preview_length))
        logger.debug("[Middleware] LLM tracing enabled")

        # Auto-configure logging level for LLM tracing module (IG-140)
        import logging

        llm_logger = logging.getLogger("soothe.middleware.llm_tracing")
        llm_logger.setLevel(logging.DEBUG)

    # 5. Execution hints (Layer 2 → Layer 1 integration)
    stack.append(ExecutionHintsMiddleware())
    logger.debug("[Middleware] Execution hints enabled")

    # 6. Workspace context (thread-aware filesystem)
    stack.append(WorkspaceContextMiddleware())
    logger.debug("[Middleware] Workspace context enabled")

    # 7. Per-turn model override (daemon / stream context) — innermost around the LLM
    stack.append(PerTurnModelMiddleware(config))
    logger.debug("[Middleware] Per-turn model override enabled")

    return tuple(stack)
