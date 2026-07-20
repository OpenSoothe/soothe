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

from soothe_nano.config.middleware_access import agent_middleware_config

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentMiddleware
    from soothe_sdk.protocols.policy import PolicyProtocol

    from soothe_nano.config import SootheConfig
    from soothe_nano.middleware._tool_context import ToolContextRegistry, ToolTriggerRegistry

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
        from soothe_nano.middleware._tool_context import ToolContextRegistry, ToolTriggerRegistry
        from soothe_nano.plugin.global_registry import get_plugin_registry

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

    1. Identity and optional outer profiling wrappers.
    2. Safety and activation chain (policy, skill, MCP).
    3. Tool-call arg capture, optimization policy, and edit coalescing.
    4. Tool reliability guards and output controls.
    5. Prompt/tool preparation (enforcement, progressive listing, system prompt).
    6. LLM call wrappers (rate-limit, optional code interpreter, workspace context).
    7. Optional inner profiling wrappers.
    8. Tool timeout wrapper.
    9. Role routing and per-turn model override.

    Args:
        config: SootheConfig with performance settings.
        policy: PolicyProtocol instance for safety enforcement.
        mcp_registry: Optional MCPRegistry for MCP tool integration (RFC-412).
    Returns:
        Tuple of middleware instances in execution order.
    """
    from soothe_deepagents.middleware.llm_rate_limit import LLMRateLimitMiddleware
    from soothe_deepagents.middleware.reliability import (
        InvalidToolHintsMiddleware,
        NetworkToolErrorsMiddleware,
        ToolOutputCapMiddleware,
    )
    from soothe_deepagents.middleware.tool_timeout import (
        ToolTimeoutMiddleware,
    )

    from .edit_coalescing import EditCoalescingMiddleware
    from .model_call_profiler import is_profiler_enabled
    from .per_turn_model import PerTurnModelMiddleware
    from .policy import SoothePolicyMiddleware
    from .system_prompt import SystemPromptMiddleware
    from .workspace_context import WorkspaceContextMiddleware

    stack: list[AgentMiddleware] = []
    profile_model_calls = is_profiler_enabled(config)

    # 1. Model call profiler (optional, for latency debugging)
    # Insert at the very start to capture full middleware chain timing
    if profile_model_calls:
        from .model_call_profiler import ModelCallProfilerMiddleware

        stack.append(ModelCallProfilerMiddleware(enabled=True))
        logger.info("[Middleware] Model call profiler enabled (outer wrapper)")

    # 2. Policy enforcement (must be first policy gate)
    if policy:
        stack.append(
            SoothePolicyMiddleware(
                policy=policy,
                profile_name=config.agent.protocols.policy.profile,
            )
        )
        logger.debug("[Middleware] Policy enforcement enabled")

    # 3. Skill activation (RFC-105: activates conditional skills on file-op path match)
    from soothe_nano.skills.index import SkillIndex
    from soothe_nano.skills.registry import ProgressiveSkillRegistry

    from .skill_activation import SkillActivationMiddleware

    _skill_index = SkillIndex()
    stack.append(
        SkillActivationMiddleware(
            registry=ProgressiveSkillRegistry(),
            catalog_provider=lambda: _skill_index.rebuild_if_stale(),
            config=config,
        )
    )
    logger.info("[Middleware] Skill activation enabled")

    # 4. MCP activation (RFC-412: search, promote, bind deferred MCP tools)
    if mcp_registry is not None:
        from .mcp_activation import MCPActivationMiddleware

        stack.append(MCPActivationMiddleware(mcp_registry=mcp_registry))
        logger.info("[Middleware] MCP activation enabled")

    # 5. Record tool-call kwargs for TUI display (IG-519).
    # The executor's stream path reads these via get_recorded_tool_call_args() to
    # attach args to wire events for step + subagent activities. Without
    # this middleware the registry stays empty and the TUI shows no tool args.
    # Must wrap EditCoalescingMiddleware (outer): coalescing intercepts edit tools
    # without calling inner handlers, so kwargs must be captured before that path.
    from .tool_call_args_middleware import ToolCallArgsMiddleware
    from .tool_optimization_middleware import ToolOptimizationMiddleware

    stack.append(ToolCallArgsMiddleware())
    logger.debug("[Middleware] Tool call args recording enabled")

    # 6. Deterministic tool optimization (reuse/dedup/search consolidation)
    stack.append(ToolOptimizationMiddleware())
    logger.debug("[Middleware] Tool optimization middleware enabled")

    # 7. Edit coalescing for parallel file edits (IG-517)
    stack.append(EditCoalescingMiddleware())
    logger.info("[Middleware] Edit coalescing enabled")

    # 8. Recoverable outbound network errors → tool messages
    stack.append(NetworkToolErrorsMiddleware())
    logger.debug("[Middleware] Network tool error recovery enabled")

    # 9. Cap tool output before graph state / model context
    tool_output = agent_middleware_config(config).tool_output
    stack.append(
        ToolOutputCapMiddleware(
            default_max_chars=int(tool_output.tool_output_max_chars),
            code_exec_max_chars=int(tool_output.code_exec_max_output_chars),
        )
    )
    logger.debug("[Middleware] Tool output cap enabled")

    # 10. Progressive builtin-tool loading (optional)
    stack.append(InvalidToolHintsMiddleware())
    logger.debug("[Middleware] Invalid tool hints enabled")

    progressive_tool_middleware = None
    if config.progressive_tools.enabled:
        from .progressive_tools import ProgressiveToolMiddleware

        progressive_tool_middleware = ProgressiveToolMiddleware(config=config)
        stack.append(progressive_tool_middleware)
        logger.info("[Middleware] Progressive tool loading enabled")

    # 11. Request-time tool enforcement (preferred_subagent routing)
    from .tool_enforcement import ToolEnforcementMiddleware

    stack.append(ToolEnforcementMiddleware())
    logger.info("[Middleware] Tool enforcement middleware enabled")

    # 12. Progressive listing prep (deferred tools/skills/MCP listing state)
    from .progressive_listing import ProgressiveListingMiddleware

    stack.append(
        ProgressiveListingMiddleware(
            config=config,
            mcp_registry=mcp_registry,
            progressive_tool_middleware=progressive_tool_middleware,
        )
    )
    logger.info("[Middleware] Progressive listing middleware enabled")

    # 13. System prompt assembly (requires routing_classification from host inject)
    trigger_registry, context_registry = _build_tool_registries(config)

    stack.append(
        SystemPromptMiddleware(
            config=config,
            tool_trigger_registry=trigger_registry,
            tool_context_registry=context_registry,
        )
    )
    logger.info("[Middleware] System prompt middleware enabled")

    # 14. Inner profiler (optional, after SystemPrompt, before rate limiter)
    # Captures timing between prompt modification and rate limiting
    if profile_model_calls:
        from .model_call_profiler import InnerModelCallProfilerMiddleware

        stack.append(InnerModelCallProfilerMiddleware(enabled=True))
        logger.info("[Middleware] Inner model call profiler enabled")

    # 15. LLM rate limiting (throttles API calls, not threads)
    # This prevents thread hanging by blocking only LLM calls, not entire threads
    llm_rl = agent_middleware_config(config).llm_rate_limit
    if llm_rl.enabled:
        stack.append(
            LLMRateLimitMiddleware(
                requests_per_minute=llm_rl.rpm_limit,
                max_concurrent_requests_per_thread=llm_rl.concurrent_limit,
                call_timeout_seconds=llm_rl.call_timeout_seconds,
                call_timeout_max_seconds=llm_rl.call_timeout_max_seconds,
                retry_on_timeout=llm_rl.retry_on_timeout,
                max_timeout_retries=llm_rl.max_timeout_retries,
                timeout_retry_multiplier=llm_rl.timeout_retry_multiplier,
                # IG-499: 429 retry configuration
                retry_on_rate_limit=llm_rl.retry_on_rate_limit,
                max_rate_limit_retries=llm_rl.max_rate_limit_retries,
                rate_limit_backoff_base=llm_rl.rate_limit_backoff_base,
                rate_limit_backoff_max=llm_rl.rate_limit_backoff_max,
                respect_retry_after_header=llm_rl.respect_retry_after_header,
                rate_limit_retry_timeout_seconds=llm_rl.rate_limit_retry_timeout_seconds,
            )
        )
        logger.info(
            "[Middleware] LLM rate limiting enabled (thread-local): rpm=%d, concurrent=%d, "
            "timeout=%ds timeout_cap=%ds retry_timeout=%s max_timeout_retries=%d multiplier=%.1f "
            "retry_429=%s max_429_retries=%d backoff_base=%.1fs backoff_max=%.1fs "
            "retry_after_header=%s rate_limit_retry_timeout=%ds",
            llm_rl.rpm_limit,
            llm_rl.concurrent_limit,
            llm_rl.call_timeout_seconds,
            llm_rl.call_timeout_max_seconds,
            llm_rl.retry_on_timeout,
            llm_rl.max_timeout_retries,
            llm_rl.timeout_retry_multiplier,
            llm_rl.retry_on_rate_limit,
            llm_rl.max_rate_limit_retries,
            llm_rl.rate_limit_backoff_base,
            llm_rl.rate_limit_backoff_max,
            llm_rl.respect_retry_after_header,
            llm_rl.rate_limit_retry_timeout_seconds,
        )
    else:
        logger.debug("[Middleware] LLM rate limiting disabled")

    # 16. Code interpreter (embedded QuickJS for programmatic tool calling)
    ci_config = config.agent.code_interpreter
    if ci_config.enabled and ci_config.ptc_allowlist:
        from .code_interpreter import CodeInterpreterMiddleware

        stack.append(CodeInterpreterMiddleware(config=config))
        logger.info(
            "[Middleware] Code interpreter enabled with ptc_allowlist=%s",
            ci_config.ptc_allowlist,
        )
    elif ci_config.enabled:
        logger.info(
            "[Middleware] Code interpreter skipped (enabled but empty ptc_allowlist; IG-506)"
        )
    else:
        logger.debug("[Middleware] Code interpreter disabled (opt-in)")

    # 17. Workspace context (thread-aware filesystem)
    stack.append(WorkspaceContextMiddleware())
    logger.debug("[Middleware] Workspace context enabled")

    # 18. LLM profiler (optional, innermost before PerTurnModelMiddleware)
    # Captures timing just before the actual model.ainvoke call
    if profile_model_calls:
        from .model_call_profiler import LLMCallProfilerMiddleware

        stack.append(LLMCallProfilerMiddleware(enabled=True))
        logger.info("[Middleware] LLM call profiler enabled (innermost wrapper)")

    # 19. Tool timeout wrapper (IG-511: prevent indefinite hangs from slow tools)
    # Positioned after other tool-related middleware, innermost around actual execution
    tool_timeout_config = agent_middleware_config(config).tool_timeout
    if tool_timeout_config.enabled:
        from soothe_nano.config.constants import DEFAULT_TASK_TIMEOUT_SECONDS

        skip_tools = (
            frozenset({"glob"})
            if tool_timeout_config.skip_tools_with_internal_timeout
            else frozenset()
        )
        stack.append(
            ToolTimeoutMiddleware(
                default_timeout_seconds=tool_timeout_config.default_seconds,
                per_tool_timeout_seconds=dict(tool_timeout_config.per_tool),
                skip_tools=skip_tools,
                honor_timeout_arg_for=frozenset({"run_command"}),
                max_timeout_seconds=float(DEFAULT_TASK_TIMEOUT_SECONDS),
            )
        )
        logger.info(
            "[Middleware] Tool timeout enabled: default=%.1fs, per_tool=%s",
            tool_timeout_config.default_seconds,
            dict(tool_timeout_config.per_tool),
        )
    else:
        logger.debug("[Middleware] Tool timeout disabled")

    # 20. Per-hop role routing (IG-545) — before per-turn override
    role_routing = config.agent.runtime.role_routing
    if role_routing.enabled:
        from .role_routing import RoleRoutingMiddleware

        stack.append(RoleRoutingMiddleware(config))
        logger.info(
            "[Middleware] Role routing enabled: orchestration=%s generation=%s max_hops=%d",
            role_routing.orchestration_model_role,
            role_routing.generation_model_role,
            role_routing.max_orchestration_hops,
        )
    else:
        logger.debug("[Middleware] Role routing disabled")

    # 21. Per-turn model override (daemon / stream context) — innermost around the LLM
    stack.append(PerTurnModelMiddleware(config))
    logger.debug("[Middleware] Per-turn model override enabled")

    return tuple(stack)
