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
    from soothe.core.context.tool_registry import ToolContextRegistry
    from soothe.core.context.trigger_registry import ToolTriggerRegistry
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
    # Tool registries always created (optimizations always enabled)
    try:
        from soothe.core.context.tool_registry import ToolContextRegistry
        from soothe.core.context.trigger_registry import ToolTriggerRegistry
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

    2. **ToolConcurrencyMiddleware** - Limits concurrent tool calls per thread
       via semaphore. LangChain's ToolNode uses asyncio.gather without limits;
       this middleware bounds parallelism to prevent resource exhaustion.

    3. **SystemPromptOptimizationMiddleware** - Modifies prompts BEFORE the
       LLM call. Requires ``routing_classification`` state injected by AgentLoop / runner
       runner during pre-stream phase. Only enabled when performance features
       are fully configured.

    4. **LLMRateLimitMiddleware** - Rate limits LLM API calls at model level,
       not thread level. Uses sliding window for RPM and semaphore for concurrent
       requests. Solves thread hanging issues from thread-level blocking.

    5. **ExecutionHintsMiddleware** - Injects Layer 2 execution hints
       (soothe_step_subagent, soothe_step_expected_output)
       into system prompt via abefore_agent hook. Runs before agent loop starts.

    6. **CodeInterpreterMiddleware** (optional) - Embedded QuickJS interpreter
       for programmatic tool calling. Enabled when ``code_interpreter.enabled``
       is True. Exposes allowlisted tools via ``tools.*`` namespace.

    7. **WorkspaceContextMiddleware** - Sets workspace ContextVar via
       abefore_agent/aafter_agent hooks. Must be set before tools run to
       enable thread-aware filesystem operations.

    8. **PerTurnModelMiddleware** - When ``attach_stream_model_override`` is set
       for the current asyncio Task (daemon per-turn ``input``), replaces the
       chat model for that stream via ``ModelRequest.override``.

    Args:
        config: SootheConfig with performance settings.
        policy: PolicyProtocol instance for safety enforcement.

    Returns:
        Tuple of middleware instances in execution order.
    """
    from .execution_hints import ExecutionHintsMiddleware
    from .llm_rate_limit import LLMRateLimitMiddleware
    from .per_turn_model import PerTurnModelMiddleware
    from .policy import SoothePolicyMiddleware
    from .system_prompt_optimization import SystemPromptOptimizationMiddleware
    from .tool_concurrency import ToolConcurrencyMiddleware
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

    # 2. Tool concurrency limit (bounds parallel tool calls per thread)
    stack.append(ToolConcurrencyMiddleware())
    max_parallel_tools = config.agent_loop.limits.max_parallel_tools
    logger.info(
        "[Middleware] Tool concurrency enabled: max_parallel_tools=%d",
        max_parallel_tools,
    )

    # 3. System prompt optimization (requires routing_classification from AgentLoop / runner)
    trigger_registry, context_registry = _build_tool_registries(config)

    stack.append(
        SystemPromptOptimizationMiddleware(
            config=config,
            tool_trigger_registry=trigger_registry,
            tool_context_registry=context_registry,
        )
    )
    logger.info("[Middleware] System prompt optimization enabled")

    # 4. LLM rate limiting (throttles API calls, not threads)
    # This prevents thread hanging by blocking only LLM calls, not entire threads
    rpm = config.agent_loop.limits.llm_rpm_limit
    concurrent = config.agent_loop.limits.llm_concurrent_limit
    timeout = config.agent_loop.limits.llm_call_timeout_seconds
    timeout_max = config.agent_loop.limits.llm_call_timeout_max_seconds
    timeout_adaptive = config.agent_loop.limits.llm_call_timeout_adaptive
    retry_on_timeout = config.agent_loop.limits.llm_retry_on_timeout
    max_timeout_retries = config.agent_loop.limits.llm_max_timeout_retries
    timeout_retry_multiplier = config.agent_loop.limits.llm_timeout_retry_multiplier

    stack.append(
        LLMRateLimitMiddleware(
            requests_per_minute=rpm,
            max_concurrent_requests_per_thread=concurrent,
            call_timeout_seconds=timeout,
            call_timeout_max_seconds=timeout_max,
            call_timeout_adaptive=timeout_adaptive,
            thread_local=True,
            retry_on_timeout=retry_on_timeout,
            max_timeout_retries=max_timeout_retries,
            timeout_retry_multiplier=timeout_retry_multiplier,
        )
    )
    logger.info(
        "[Middleware] LLM rate limiting enabled (thread-local): rpm=%d, concurrent=%d, "
        "timeout_floor=%ds timeout_cap=%ds adaptive=%s retry=%s max_retries=%d multiplier=%.1f",
        rpm,
        concurrent,
        timeout,
        timeout_max,
        timeout_adaptive,
        retry_on_timeout,
        max_timeout_retries,
        timeout_retry_multiplier,
    )

    # 5. Execution hints (Layer 2 → Layer 1 integration)
    stack.append(ExecutionHintsMiddleware())
    logger.debug("[Middleware] Execution hints enabled")

    # 6. Code interpreter (embedded QuickJS for programmatic tool calling)
    if config.code_interpreter.enabled:
        from .code_interpreter import CodeInterpreterMiddleware

        stack.append(CodeInterpreterMiddleware(config=config))
        logger.info(
            "[Middleware] Code interpreter enabled with ptc_allowlist=%s",
            config.code_interpreter.ptc_allowlist,
        )
    else:
        logger.debug("[Middleware] Code interpreter disabled (opt-in)")

    # 7. Workspace context (thread-aware filesystem)
    stack.append(WorkspaceContextMiddleware())
    logger.debug("[Middleware] Workspace context enabled")

    # 8. Per-turn model override (daemon / stream context) — innermost around the LLM
    stack.append(PerTurnModelMiddleware(config))
    logger.debug("[Middleware] Per-turn model override enabled")

    return tuple(stack)
