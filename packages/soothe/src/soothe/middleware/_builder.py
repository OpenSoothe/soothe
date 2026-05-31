"""Middleware stack construction for CoreAgent.

Defines the Soothe middleware layer.
Note: ParallelToolsMiddleware removed - langchain handles tool parallelism
via asyncio.gather in ToolNode.

This module provides a single function to build the middleware stack
in the correct order with proper dependency handling.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

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
    mcp_registry: Any | None = None,
) -> tuple[AgentMiddleware, ...]:
    """Build Soothe middleware stack in correct order.

    The middleware order is intentional and follows dependency requirements:

    1. **SoothePolicyMiddleware** - Blocks unsafe actions FIRST before any
       other middleware processes them. Uses PolicyProtocol.check() on every
       tool/subagent call.

    2. **ToolConcurrencyMiddleware** - Limits concurrent tool calls per thread
       via semaphore. LangChain's ToolNode uses asyncio.gather without limits;
       this middleware bounds parallelism to prevent resource exhaustion.

    3. **SystemPromptMiddleware** - Modifies prompts BEFORE the
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
    from .system_prompt import SystemPromptMiddleware
    from .tool_concurrency import ToolConcurrencyMiddleware
    from .tool_network_errors import NetworkToolErrorsMiddleware
    from .workspace_context import WorkspaceContextMiddleware

    stack: list[AgentMiddleware] = []

    # 1. Policy enforcement (must be first to block unsafe actions)
    if policy:
        stack.append(
            SoothePolicyMiddleware(
                policy=policy,
                profile_name=config.agent.protocols.policy.profile,
            )
        )
        logger.debug("[Middleware] Policy enforcement enabled")

    # 1b. Skill activation (RFC-105: activates conditional skills on file-op path match)
    from soothe.skills.index import SkillIndex
    from soothe.skills.registry import ProgressiveSkillRegistry

    from .skill_activation import SkillActivationMiddleware

    _skill_index = SkillIndex()
    stack.append(
        SkillActivationMiddleware(
            registry=ProgressiveSkillRegistry(),
            catalog_provider=lambda: _skill_index.rebuild_if_stale(),
            config=config,
        )
    )
    logger.info("[Middleware] Skill activation (RFC-105) enabled")

    # 1c. MCP tool search (RFC-412: MCP progressive disclosure telemetry)
    if mcp_registry is not None:
        from .mcp_tool_search import MCPToolSearchMiddleware

        stack.append(MCPToolSearchMiddleware(mcp_registry=mcp_registry))
        logger.info("[Middleware] MCP tool search (RFC-412) enabled")

    # 2. Tool concurrency limit (bounds parallel tool calls per thread)
    stack.append(ToolConcurrencyMiddleware())
    max_parallel_tools = config.agent.loop.limits.max_parallel_tools
    logger.info(
        "[Middleware] Tool concurrency enabled: max_parallel_tools=%d",
        max_parallel_tools,
    )

    # 2b. Recoverable outbound network errors → tool messages (TLS verify, connection refused)
    stack.append(NetworkToolErrorsMiddleware())
    logger.debug("[Middleware] Network tool error recovery enabled")

    # 3. System prompt assembly (requires routing_classification from AgentLoop / runner)
    trigger_registry, context_registry = _build_tool_registries(config)

    stack.append(
        SystemPromptMiddleware(
            config=config,
            tool_trigger_registry=trigger_registry,
            tool_context_registry=context_registry,
            mcp_registry=mcp_registry,
        )
    )
    logger.info("[Middleware] System prompt middleware enabled")

    # 4. LLM rate limiting (throttles API calls, not threads)
    # This prevents thread hanging by blocking only LLM calls, not entire threads
    rpm = config.agent.loop.limits.llm_rpm_limit
    concurrent = config.agent.loop.limits.llm_concurrent_limit
    timeout = config.agent.loop.limits.llm_call_timeout_seconds
    timeout_max = config.agent.loop.limits.llm_call_timeout_max_seconds
    timeout_adaptive = config.agent.loop.limits.llm_call_timeout_adaptive
    retry_on_timeout = config.agent.loop.limits.llm_retry_on_timeout
    max_timeout_retries = config.agent.loop.limits.llm_max_timeout_retries
    timeout_retry_multiplier = config.agent.loop.limits.llm_timeout_retry_multiplier

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
    if config.agent.code_interpreter.enabled:
        from .code_interpreter import CodeInterpreterMiddleware

        stack.append(CodeInterpreterMiddleware(config=config))
        logger.info(
            "[Middleware] Code interpreter enabled with ptc_allowlist=%s",
            config.agent.code_interpreter.ptc_allowlist,
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
